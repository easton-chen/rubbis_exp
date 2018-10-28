#!/usr/bin/env python
from __future__ import print_function, division

import datetime
import logging
from math import ceil,cos,e,pi
from optparse import OptionParser
import os
import select
import socket
from sys import stderr
from time import sleep
import time
import random
import copy

# Controller logic
def executeController(pole, setPoint, serviceTime, serviceLevel):
	# special value: no control
	if pole == 0:
		return serviceLevel

	alpha = serviceTime / serviceLevel # very rough estimate
	# NOTE: control knob allowing to smooth service times
	# To enable this, you *must* add a new state variable (alpha) to the controller.
	#alpha = 0.5 * alpha + 0.5 * serviceTime / previousServiceLevel # very rough estimate
	error = setPoint - serviceTime
	# NOTE: control knob allowing slow increase
	if error > 0:
		error *= 0.1
	serviceLevel = serviceLevel + (1 / alpha) * (1 - pole) * error

	# saturation, service level is a probability
	serviceLevel = max(serviceLevel, 0.0)
	serviceLevel = min(serviceLevel, 1.0)
	return serviceLevel
# end controller logic

def now():
	return time.time()

def avg(a):
	if len(a) == 0:
		return float('nan')
	return sum(a) / len(a)

def median(a):
	# assumes a is sorted
	n = len(a)
	if n == 0:
		return float('nan')
	if n % 2 == 0:
		return (a[n//2-1] + a[n//2]) / 2
	else:
		return a[n//2]

def quartiles(a):
	n = len(a)
	if n == 0:
		return [ float('nan') ] * 6
	if n == 1:
		return [ a[0] ] * 6

	a = sorted(a)
	ret = []
	ret.append(a[0])
	ret.append(median(a[:n//2]))
	ret.append(median(a))
	ret.append(median(a[n//2:]))
	ret.append(a[-1])
	ret.append(avg(a))

	return ret

def getNumberRequestsHigherLatency(latencies, setPoint):
	compteur = 0
	for i in latencies:
		if i>setPoint:
			compteur += 1
	p_timeout = compteur/(len(latencies))
	p_timeout *= 10	
	return 1/(e**p_timeout)

def getAverageServiceTime(latencies, setPoint):
	p_avg = avg(latencies)/setPoint
	a = 0.99290
	b = 0.08692
	c = -1.12247 
	res = a + b * p_avg + c * p_avg * p_avg
	return max(0, res)

class UnixTimeStampFormatter(logging.Formatter):
	def formatTime(self, record, datefmt = None):
		return "{0:.6f}".format(record.created)

def main():
	# Set up logging
	logChannel = logging.StreamHandler()
	logChannel.setFormatter(UnixTimeStampFormatter("%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s"))
	logging.getLogger().addHandler(logChannel)
	logging.getLogger().setLevel(logging.DEBUG)

	# Parse command-line
	parser = OptionParser()
	parser.add_option("--pole"    , type="float", help="use this pole value (default: %default)", default = 0.9)
	parser.add_option("--setPoint", type="float", help="keep maximum latency around this value (default: %default)", default = 1)
	parser.add_option("--serviceLevel", type="float", help="service level (default: %default)", default = 0.5)
	parser.add_option("--cap", type="int", help="max CPU usage (default: %default)", default = 400)
	parser.add_option("--concurrency", type="int", help="http client thread (default: %default)", default = 100)
	parser.add_option("--thinktime", type="float", help="http client think time (default: %default)", default = 1)
	parser.add_option("--controlInterval", type="float", help="time between control iterations (default: %default)", default = 2)
	parser.add_option("--measureInterval", type="float", help="act based on maximum latency this far in the past (default: %default)", default = 3)
	parser.add_option("--rmIp", type="string", help="send matching values to this IP (default: %default)", default = "192.168.122.1")
	parser.add_option("--rmPort", type="int", help="send matching values to this UDP port (default: %default)", default = 2712)
	parser.add_option("--preference", type="int", help="user preference of response time, serviceLevel and timeout (default: %default)", default = 0)
	parser.add_option("--w0", type="float", help="", default = 0.33)
	parser.add_option("--w1", type="float", help="", default = 0.33)
	parser.add_option("--w2", type="float", help="", default = 0.33)
	(options, args) = parser.parse_args()

	# Setup socket to listen for latency reports
	appSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	appSocket.bind(("localhost", 2712))

	# Setup socket to send matching values
	rmSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

	# Initialize control loop
	poll = select.poll()
	poll.register(appSocket, select.POLLIN)
	lastControl = now()
	lastTotalRequests = 0
	timestampedLatencies = [] # tuples of timestamp, latency
	totalRequests = 0
	serviceLevel = 0.5
    	lastServiceLevel = 0
	cap = options.cap
	concurrency = options.concurrency
	thinktime = options.thinktime
	setPoint = options.setPoint
    	flag = 0
        preference_order_list = [[0,1,2],[0,2,1],[1,0,2],[1,2,0],[2,0,1],[2,1,0]]
	preference_order = preference_order_list[options.preference]
        weights = [0, 0, 0]
	weights = [0, 0, 0]
	weights[0] = options.w0
	weights[1] = options.w1
	weights[2] = options.w2


	# Control loop
	while True:
        	
		# Wait for next control iteration or message from application
		waitFor = max(ceil((lastControl + options.controlInterval - now()) * 1000), 1)
		events = poll.poll(waitFor)

		_now = now() # i.e., all following operations are "atomic" with respect to time
		# If we received a latency report, record it
		if events:
			data, address = appSocket.recvfrom(4096, socket.MSG_DONTWAIT)
			timestampedLatencies.append((_now, float(data)))
			totalRequests += 1

		# Run control algorithm if it's time for it
		if _now - lastControl >= options.controlInterval:
			# Filter latencies: only take those from the measure interval
			timestampedLatencies = [ (t, l)
				for t, l in timestampedLatencies if t > _now - options.measureInterval ]
			latencies = [ l for t,l in timestampedLatencies ]

			# Do we have new reports?
			if latencies:
                                # if converge        
                                if abs(serviceLevel - lastServiceLevel) <= 0.01:
        	    	                flag += 1
				else:
					flag = 0
        	                if flag == 3:
                                        y1 = getNumberRequestsHigherLatency(latencies, setPoint)
                                        y2 = serviceLevel
                                        y3 = getAverageServiceTime(latencies, setPoint)
                                        Y = y1 * weights[0] + y2 * weights[1] + y3 * weights[2]
                                        line = ','.join([str(options.preference), str(cap), str(concurrency),str(Y),str(latencyStat[5])]) + '\n'
                                        line = 'data: ' + line
                                        logging.info(line)
                                        break
				# Execute controller
                		lastServiceLevel = serviceLevel
				serviceLevel = executeController(
					pole = options.pole,
					setPoint = options.setPoint,
					serviceTime = max(latencies),
					serviceLevel = serviceLevel,
				)
				
				# Report performance to RM
				matchingValue = min([ 1 - latency / options.setPoint for latency in latencies ])
				rmSocket.sendto(str(matchingValue), (options.rmIp, options.rmPort))

				# Print statistics
				latencyStat = quartiles(latencies)
				logging.info("latency={0:.0f}:{1:.0f}:{2:.0f}:{3:.0f}:{4:.0f}:({5:.0f})ms throughput={6:.0f}rps rr={7:.2f}% total={8} perf={9:.3f} conv?={10}".format(
					latencyStat[0] * 1000,
					latencyStat[1] * 1000,
					latencyStat[2] * 1000,
					latencyStat[3] * 1000,
					latencyStat[4] * 1000,
					latencyStat[5] * 1000,
					(totalRequests - lastTotalRequests) / (_now-lastControl),
					serviceLevel * 100,
					totalRequests,
					matchingValue,
					lastServiceLevel - serviceLevel
				))
				with open('/tmp/serviceLevel.tmp', 'w') as f:
					print(serviceLevel, file = f)
				os.rename('/tmp/serviceLevel.tmp', '/tmp/serviceLevel')
			else:
				logging.info("No traffic since last control interval.")
			lastControl = _now
			lastTotalRequests = totalRequests
	

if __name__ == "__main__":
	main()
