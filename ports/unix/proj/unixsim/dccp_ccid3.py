#!/usr/bin/python

import pcap
import dpkt
import logging
from optparse import OptionParser

DEFAULT_IFACE='eth0'
PORT=8081
PKT_SIZE=1024

unacked = {}
rtts = []
times = []
rcvd_pkts=[]
rtt_avg = 0
weights = [1,1,1,1,0.8,0.6,0.4,0.2]
s_intervals = []

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

# maintain history of the last 8 loss events
def add_loss_interval(loss_interval_sample):
    global s_intervals
    s_intervals.insert(0, loss_interval_sample)
    if len(s_intervals) > 8:
        s_intervals = s_intervals[0:7]

# calculates the average loss p, used for throughput calculation.
def get_avg_loss_prop():
    global s_intervals
    _avg_loss = float(sum([i*j for i,j in zip(weights,s_intervals)]))/float(sum(weights[0:len(s_intervals)]))
    return 1.0/_avg_loss
    


# check if the sample makes sense.
# If it does, returen the running average.
def get_avg_rtt(avg, rtt_sample):
    if (rtt_sample < 0 or rtt_sample > 3):
        logging.warn("non-sense RTT : %f" % rtt_sample)
        return avg
    if avg > 0:
        return (0.9*avg + 0.1*rtt_sample)
    else:
        return rtt_sample

class IfListener(object):
    def __init__(self, iface, is_receiver):
        self.s_a = 0
        self.rtt_avg = 0
        self.p = pcap.pcap(iface)
        self.p.setfilter("port %d" % PORT)
#        self.setup_recv_raw_socket(iface)
        dispatched = 1
        while(dispatched == 1):
            if (is_receiver):
                logging.info("Running on the receiver side")
                dispatched = self.p.dispatch(0, self.receiver_handle_packet)
                try:
                    self.p.loop(self.receiver_handle_packet)
                except KeyboardInterrupt:
                    logging.warn("Plot something here")
            else:
                logging.info("Running on the sender side")
                dispatched = self.p.dispatch(0, self.sender_handle_packet)
                try:
                    self.p.loop(self.sender_handle_packet)
                except KeyboardInterrupt:
                    logging.warn("Plot something here")

    def sender_handle_packet(self, timestamp, pkt):
        tcp_hdr = dpkt.ethernet.Ethernet(pkt).data.data
        if tcp_hdr.flags & dpkt.tcp.TH_ACK and tcp_hdr.dport == PORT:
            try:
                _sent = unacked[int(tcp_hdr.ack)]
                times.append(timestamp)
                rtt = timestamp - _sent
                rtts.append(rtt)
                self.rtt_avg = get_avg_rtt(self.rtt_avg, rtt)
                logging.info("Current RTT average : %f" % self.rtt_avg)
                # print "Received ack %d at %f" % (tcp_hdr.ack, timestamp)
            except KeyError:
                pass
                # print "Could not find seq %d" % (int(tcp_hdr.ack))
        else:
            # print "Sending packet %d at %d" % (tcp_hdr.seq, timestamp)
            unacked[int(tcp_hdr.seq)] = timestamp

    def receiver_handle_packet(self, timestamp, pkt):
        tcp_hdr = dpkt.ethernet.Ethernet(pkt).data.data
        if tcp_hdr.sport == PORT and (tcp_hdr.flags & dpkt.tcp.TH_SYN == 0):
            if len(rcvd_pkts) > 0:
                if(tcp_hdr.seq < rcvd_pkts[-1][0]):
                    logging.warn("This seems like a rtxmit - ignoring...")
                    return
                _gap = tcp_hdr.seq - rcvd_pkts[-1][1]
                if (_gap > 1):
                    _lost = rcvd_pkts[-1][1]
                    if self.s_a != 0:
                        interval = (_lost - self.s_a)/1024
                        add_loss_interval(interval)
                        logging.info("Lost packet detected - current p_loss estimate:%f" % get_avg_loss_prop()) 
                    self.s_a = rcvd_pkts[-1][1]
                    # logging.info("Missing %d bytes (%d packets) in the between" % (_gap, _gap/PKT_SIZE))
                
            
            rcvd_pkts.append((tcp_hdr.seq, tcp_hdr.seq + len(tcp_hdr.data)))
            # print "Received packet of size %d" % len(tcp_hdr.data)

            
if __name__ == "__main__":
    usage = "usage: %prog [options] arg"
    description = "Update firmware to remote APs"
    parser = OptionParser(usage)
    parser.description = description
    parser.add_option("-r","--receiver",dest="is_receiver",action="store_true", default=False,
                      help="Script running on the receiver side (calculate p_loss instead of RTT")

    (options, args) = parser.parse_args()

    IfListener(DEFAULT_IFACE, options.is_receiver)