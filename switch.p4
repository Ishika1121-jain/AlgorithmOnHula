/* -*- P4_16 -*- */
#include <core.p4>
#include <v1model.p4>

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;
typedef bit<9> port_id_t;
typedef bit<8> util_t;
typedef bit<24> tor_id_t;
typedef bit<48> time_t;

/* Constants about the topology and switches. */
const port_id_t NUM_PORTS = 255;
const tor_id_t NUM_TORS = 512;
const bit<32> EGDE_HOSTS = 4;

/* Declaration for the various packet types. */
const bit<16> TYPE_IPV4 = 0x800;
const bit<8> PROTO_HULA = 0x42;
const bit<8> PROTO_TCP = 0x06;

/* Tracking things for flowlets */
const time_t FLOWLET_TOUT = 48w1 << 3;
const util_t PROBE_FREQ_FACTOR = 6;
const time_t KEEP_ALIVE_THRESH = 48w1 << PROBE_FREQ_FACTOR;
const time_t PROBE_FREQ = 48w1 << PROBE_FREQ_FACTOR; // Here for documentation. Unused.
const util_t UTIL_CHANGE_THRESH = 8;

/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/

const bit<8> AGG_SIZE = 4;

header hula_t {
    bit<24> dst_tor0;
    bit<8>  path_util0;

    bit<24> dst_tor1;
    bit<8>  path_util1;

    bit<24> dst_tor2;
    bit<8>  path_util2;

    bit<24> dst_tor3;
    bit<8>  path_util3;
    
    // Telemetry: queue depth (in bytes, max 255)
    bit<8>  queue_depth;
    
    // Telemetry: TX Link Utilization (INT spec: units of 1/256 of link bandwidth, 0-255 scale)
    bit<8>  tx_link_util;
    
    // Telemetry: Flow Completion Time (FCT) tracking
    bit<48> flow_start_time;    // When flow was first seen (ingress_global_timestamp)
    bit<48> flow_current_time;  // Current packet's timestamp (ingress_global_timestamp)
}



header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header ipv4_t {
    bit<4>    version;
    bit<4>    ihl;
    bit<8>    diffserv;
    bit<16>   totalLen;
    bit<16>   identification;
    bit<3>    flags;
    bit<13>   fragOffset;
    bit<8>    ttl;
    bit<8>    protocol;
    bit<16>   hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

header tcp_t {
  bit<16> srcPort;
  bit<16> dstPort;
  bit<32> seq;
  bit<32> ack;
  bit<4> dataofs;
  bit<3> reserved;
  bit<9> flags;
  bit<32> window;
  bit<16> chksum;
  bit<16> urgptr;
}

struct metadata {
    bit<9> nxt_hop;
    bit<32> self_id;
    bit<32> dst_tor;
}

struct headers {
    ethernet_t   ethernet;
    ipv4_t       ipv4;
    tcp_t        tcp;
    hula_t       hula;
}

/*************************************************************************
*********************** P A R S E R  ***********************************
*************************************************************************/

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            TYPE_IPV4: parse_ipv4;
            default: accept;
        }
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
          PROTO_HULA: parse_hula;
          PROTO_TCP: parse_tcp;
          default: accept;
        }
    }

    state parse_hula {
        packet.extract(hdr.hula);
        transition accept;
    }

    state parse_tcp {
        packet.extract(hdr.tcp);
        transition accept;
    }

}

/*************************************************************************
************   C H E C K S U M    V E R I F I C A T I O N   *************
*************************************************************************/

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {  }
}


/*************************************************************************
**************  I N G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    /****** Registers to keep track of utilization. *******/

    // Keep track of the port utilization
    register<util_t>((bit<32>) NUM_PORTS) port_util;
    // Last time port_util was updated for a port.
    register<time_t>((bit<32>) NUM_PORTS) port_util_last_updated;
    
    // Keep track of the last time a probe from dst_tor came.
    register<time_t>((bit<32>) NUM_TORS) update_time;
    // Best hop for for each tor
    register<port_id_t>((bit<32>) NUM_TORS) best_hop;
    // Last time a packet from a flowlet was observed.
    register<time_t>((bit<32>) 1024) flowlet_time;
    // The next hop a flow should take.
    register<port_id_t>((bit<32>) 1024) flowlet_hop;
    // Keep track of the minimum utilized path
    register<util_t>((bit<32>) NUM_TORS) min_path_util;
    
    // NEW: FCT Flow Tracking Registers
    // Store flow start time (first packet timestamp) indexed by flow hash
    register<time_t>((bit<32>) 1024) flow_start_time_reg;

    action drop() {
        mark_to_drop(standard_metadata);
    }

    /******************************************************/
    
    /**** NEW: Flow Completion Time (FCT) Tracking *****/
    action track_flow_fct() {
        // Compute flow hash based on 5-tuple
        bit<32> flow_hash;
        hash(flow_hash, HashAlgorithm.csum16, 32w0, {
            hdr.ipv4.srcAddr,
            hdr.ipv4.dstAddr,
            hdr.ipv4.protocol,
            hdr.tcp.srcPort,
            hdr.tcp.dstPort
        }, 32w1 << 10 - 1);
        
        time_t curr_time = standard_metadata.ingress_global_timestamp;
        time_t flow_start;
        
        // Read the stored flow start time
        flow_start_time_reg.read(flow_start, flow_hash);
        
        // If flow_start is 0, this is the first packet of the flow
        // Record current time as flow start
        bool is_new_flow = (flow_start == 0);
        time_t start_time = is_new_flow ? curr_time : flow_start;
        flow_start_time_reg.write(flow_hash, start_time);
        
        // Store FCT information in telemetry header
        if (hdr.hula.isValid()) {
            hdr.hula.flow_start_time = start_time;
            hdr.hula.flow_current_time = curr_time;
        }
    }

    /******************************************************/

    /**** Core HULA logic *****/

    action hula_handle_probe() {
        time_t curr_time = standard_metadata.ingress_global_timestamp;
        util_t tx_util;
        port_util.read(tx_util, (bit<32>) standard_metadata.ingress_port);
        

        /* ---------- ENTRY 0 ---------- */
        {
            bit<32> dst = (bit<32>) hdr.hula.dst_tor0;

            util_t mpu;
            time_t up_time;

            min_path_util.read(mpu, dst);
            update_time.read(up_time, dst);

            util_t new_util = hdr.hula.path_util0;
            new_util = (new_util < tx_util) ? tx_util : new_util;


            bool cond = (new_util < mpu ||
                        curr_time - up_time > KEEP_ALIVE_THRESH);

            mpu = cond ? new_util : mpu;
            min_path_util.write(dst, mpu);

            up_time = cond ? curr_time : up_time;
            update_time.write(dst, up_time);

            port_id_t bh;
            best_hop.read(bh, dst);
            bh = cond ? standard_metadata.ingress_port : bh;
            best_hop.write(dst, bh);

            hdr.hula.path_util0 = mpu;
        }

        /* ---------- ENTRY 1 ---------- */
        {
            bit<32> dst = (bit<32>) hdr.hula.dst_tor1;

            util_t mpu;
            time_t up_time;

            min_path_util.read(mpu, dst);
            update_time.read(up_time, dst);

            util_t new_util = hdr.hula.path_util1;
            new_util = (new_util < tx_util) ? tx_util : new_util;

            bool cond = (new_util < mpu ||
                        curr_time - up_time > KEEP_ALIVE_THRESH);

            mpu = cond ? new_util : mpu;
            min_path_util.write(dst, mpu);

            up_time = cond ? curr_time : up_time;
            update_time.write(dst, up_time);

            port_id_t bh;
            best_hop.read(bh, dst);
            bh = cond ? standard_metadata.ingress_port : bh;
            best_hop.write(dst, bh);

            hdr.hula.path_util1 = mpu;
        }

        /* ---------- ENTRY 2 ---------- */
        {
            bit<32> dst = (bit<32>) hdr.hula.dst_tor2;

            util_t mpu;
            time_t up_time;

            min_path_util.read(mpu, dst);
            update_time.read(up_time, dst);

            util_t new_util = hdr.hula.path_util2;
            new_util = (new_util < tx_util) ? tx_util : new_util;


            bool cond = (new_util < mpu ||
                        curr_time - up_time > KEEP_ALIVE_THRESH);

            mpu = cond ? new_util : mpu;
            min_path_util.write(dst, mpu);

            up_time = cond ? curr_time : up_time;
            update_time.write(dst, up_time);

            port_id_t bh;
            best_hop.read(bh, dst);
            bh = cond ? standard_metadata.ingress_port : bh;
            best_hop.write(dst, bh);

            hdr.hula.path_util2 = mpu;
        }

        /* ---------- ENTRY 3 ---------- */
        {
            bit<32> dst = (bit<32>) hdr.hula.dst_tor3;

            util_t mpu;
            time_t up_time;

            min_path_util.read(mpu, dst);
            update_time.read(up_time, dst);

            util_t new_util = hdr.hula.path_util3;
            new_util = (new_util < tx_util) ? tx_util : new_util;


            bool cond = (new_util < mpu ||
                        curr_time - up_time > KEEP_ALIVE_THRESH);

            mpu = cond ? new_util : mpu;
            min_path_util.write(dst, mpu);

            up_time = cond ? curr_time : up_time;
            update_time.write(dst, up_time);

            port_id_t bh;
            best_hop.read(bh, dst);
            bh = cond ? standard_metadata.ingress_port : bh;
            best_hop.write(dst, bh);

            hdr.hula.path_util3 = mpu;
        } 
    }

    action hula_handle_data_packet() {
        time_t curr_time = standard_metadata.ingress_global_timestamp;
        bit<32> dst_tor = meta.dst_tor;

        util_t tx_util;
        port_util.read(tx_util, (bit<32>) standard_metadata.ingress_port);

        bit<32> flow_hash;
        time_t flow_t;
        port_id_t flow_h;
        port_id_t best_h;

        // Compute flow hash BEFORE modifying headers (while protocol is still TCP=0x06)
        hash(flow_hash, HashAlgorithm.csum16, 32w0, {
            hdr.ipv4.srcAddr,
            hdr.ipv4.dstAddr,
            hdr.ipv4.protocol,
            hdr.tcp.srcPort,
            hdr.tcp.dstPort
        }, 32w1 << 10 - 1);

        flowlet_time.read(flow_t, flow_hash);

        /*if (curr_time - flow_t > FLOWLET_TOUT) {*/
        best_hop.read(best_h, meta.dst_tor);
        port_id_t tmp;
        flowlet_hop.read(tmp, flow_hash);
        tmp = (curr_time - flow_t > FLOWLET_TOUT) ? best_h : tmp;
        flowlet_hop.write(flow_hash, tmp);
        /*}*/

        flowlet_hop.read(flow_h, flow_hash);
        standard_metadata.egress_spec = flow_h;
        flowlet_time.write(flow_hash, curr_time);
        
        // NOW add HULA header to data packets for telemetry (after flow decision)
        hdr.hula.setValid();
        hdr.hula.dst_tor0 = 0;
        hdr.hula.path_util0 = 0;
        hdr.hula.dst_tor1 = 0;
        hdr.hula.path_util1 = 0;
        hdr.hula.dst_tor2 = 0;
        hdr.hula.path_util2 = 0;
        hdr.hula.dst_tor3 = 0;
        hdr.hula.path_util3 = 0;
        hdr.hula.queue_depth = 0;      // Will be populated in egress
        hdr.hula.tx_link_util = 0;     // Will be populated in egress
        hdr.hula.flow_start_time = curr_time;
        hdr.hula.flow_current_time = curr_time;
        
        // Change protocol to HULA (0x42) to indicate telemetry header present
        hdr.ipv4.protocol = PROTO_HULA;
    }

    table hula_logic {
        key = {
          hdr.ipv4.protocol: exact;
        }
        actions = {
          hula_handle_probe;
          hula_handle_data_packet;
          drop;
        }
        size = 4;
        default_action = drop();
    }

    /***********************************************/

    /***** Implement mapping from dstAddr to dst_tor ********/
    // Uses the destination address to compute the destination tor and the id of
    // current switch. The table is configured by the control plane.
    action set_dst_tor(tor_id_t dst_tor, tor_id_t self_id) {
        meta.dst_tor = (bit<32>) dst_tor;
        meta.self_id = (bit<32>) self_id;
    }

    // Used when matching a probe packet.
    action dummy_dst_tor() {
        meta.dst_tor = 0;
        meta.self_id = 1;
    }

    table get_dst_tor {
        key= {
          hdr.ipv4.dstAddr: exact;
        }
        actions = {
          set_dst_tor;
          dummy_dst_tor;
        }
        default_action = dummy_dst_tor;
    }

    /***********************/

    /********* Implement forwarding for edge nodes. ********/
    action simple_forward(egressSpec_t port) {
        standard_metadata.egress_spec = port;
    }

    table edge_forward {
        key = {
          hdr.ipv4.dstAddr: exact;
        }
        actions = {
          simple_forward;
          drop;
        }
        size = EGDE_HOSTS;
        default_action = drop();
    }

    /******************************************************/

    action update_ingress_statistics() {
      util_t util;
      time_t last_update;

      time_t curr_time = standard_metadata.ingress_global_timestamp;
      bit<32> port= (bit<32>) standard_metadata.ingress_port;
      
      port_util.read(util, port);
      port_util_last_updated.read(last_update, port);

      bit<8> delta_t = (bit<8>) (curr_time - last_update);
      util_t old_util = util;

    util = (((bit<8>) standard_metadata.packet_length + util) << PROBE_FREQ_FACTOR) - delta_t;
    util = util >> PROBE_FREQ_FACTOR;

    port_util.write(port, util);
    port_util_last_updated.write(port, curr_time);

    /* --- NEW: Trigger faster refresh if utilization changed a lot --- */
    bool trigger;

    trigger = ((util > old_util && util - old_util > UTIL_CHANGE_THRESH) ||
            (old_util > util && old_util - util > UTIL_CHANGE_THRESH));

    time_t old_update;
    update_time.read(old_update, (bit<32>) meta.dst_tor);

    time_t new_update = trigger ? 0 : old_update;

    update_time.write((bit<32>) meta.dst_tor, new_update);


    }

    apply {
        drop();
        get_dst_tor.apply();
        update_ingress_statistics();
        if (hdr.ipv4.isValid()) {
          track_flow_fct();  // NEW: Track FCT for every packet
          hula_logic.apply();
          if (hdr.hula.isValid()) {
            standard_metadata.mcast_grp = (bit<16>)standard_metadata.ingress_port;
          }
          if (meta.dst_tor == meta.self_id) {
              edge_forward.apply();
          }
        }
    }
}

/*************************************************************************
****************  E G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {
        // Populate queue_depth telemetry from egress queue occupancy
        // enq_qdepth: queue depth when packet arrived at egress queue
        // deq_qdepth: queue depth when packet departed egress queue
        // We use deq_qdepth (queue occupancy at dequeue time) as it shows current congestion
        if (hdr.hula.isValid()) {
            // Cast deq_qdepth to bit<8>. deq_qdepth is bit<19> in BMv2
            // so we saturate to 0-255 range for telemetry
            bit<19> queue_occ = standard_metadata.deq_qdepth;
            // Saturating cast: if queue > 255, cap at 255
            hdr.hula.queue_depth = (bit<8>)(queue_occ > 255 ? 255 : queue_occ);
            
            // Calculate TX Link Utilization (INT spec: 0-255 scale, 255 = 100% bandwidth utilization)
            // Approach: Use queue-depth-based approximation
            // avg_queue = (enq_qdepth + deq_qdepth) / 2
            // tx_link_util = scaled avg_queue into 0-255 range
            
            bit<19> enq_q = standard_metadata.enq_qdepth;  // Queue depth at enqueue
            bit<19> deq_q = standard_metadata.deq_qdepth;  // Queue depth at dequeue
            
            // Calculate average: (enq_qdepth + deq_qdepth) / 2
            // Use bit<20> to avoid overflow during addition of two bit<19> values
            bit<20> sum_q = (bit<20>)enq_q + (bit<20>)deq_q;
            bit<20> avg_q = sum_q >> 1;  // Divide by 2
            
            // Scale to 0-255 range based on maximum link capacity
            // Assume max queue depth is ~2048 bytes (reasonable for BMv2)
            // This maps: avg_q / 2048 * 256 = avg_q * 256 / 2048 = avg_q * 0.125 = avg_q >> 3
            // Result is bit<17> max, which safely fits in bit<8>
            bit<17> scaled_util = (bit<17>)avg_q >> 3;  // Divide by 8 to scale to 256 level
            
            // Saturating cast to bit<8>: if scaled > 255, cap at 255
            hdr.hula.tx_link_util = (bit<8>)(scaled_util > 255 ? 255 : scaled_util);
        }
    }
}

/*************************************************************************
*************   C H E C K S U M    C O M P U T A T I O N   **************
*************************************************************************/

control MyComputeChecksum(inout headers  hdr, inout metadata meta) {
     apply {
        update_checksum(
            hdr.ipv4.isValid(),
            { hdr.ipv4.version,
              hdr.ipv4.ihl,
              hdr.ipv4.diffserv,
              hdr.ipv4.totalLen,
              hdr.ipv4.identification,
              hdr.ipv4.flags,
              hdr.ipv4.fragOffset,
              hdr.ipv4.ttl,
              hdr.ipv4.protocol,
              hdr.ipv4.srcAddr,
              hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16);
    }
}

/*************************************************************************
***********************  D E P A R S E R  *******************************
*************************************************************************/

control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.hula);      // Emit HULA before TCP (comes right after IPv4)
        packet.emit(hdr.tcp);
    }
}

/*************************************************************************
***********************  S W I T C H  *******************************
*************************************************************************/

V1Switch(
MyParser(),
MyVerifyChecksum(),
MyIngress(),
MyEgress(),
MyComputeChecksum(),
MyDeparser()
) main;
