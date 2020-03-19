#!/usr/bin/python

# apt-get install wkhtmltopdf
#pip install imgkit

#from selenium import webdriver
import requests
import imgkit
#from selenium.webdriver.support.ui import WebDriverWait
import sys
import time
import os

fails = []

def capture(url):
	ip = url.split("//")[1]
	options = {'quiet':'','height':768,'width':1024}
	mline = "<hr><br><b>%s</b>" % (url)
	write_html(mline,outfile)

	try:
		r = requests.get(url, verify=False, allow_redirects=True,timeout=60)
		for keys,values in r.headers.items():
			mline =  "<br><b>%s:%s</b>"%(keys,values)
			write_html(mline,outfile)
		content = str(r.content)
		# print content
		imgkit.from_string(content,ip+".png",options=options)
		mline = "<br><b><a href='%s'><img src='%s.png' height='400'></a><hr>" %(url,ip)
		write_html(mline,outfile)
	except Exception as e:
		write_fail(url)
		mline = "<br>Failed: <a href='%s'>%s</a>" % (url,url)
		write_html(mline,outfile)
		print "*** FAILED: %s *** (you know what you did)" % (url)
		print str(e)


def write_html(mline,outfile):
	with open (outfile+'.html','a+') as f:
		f.write(mline+"\n")


def write_fail(url):
	with open('failed_urls.txt','a+') as fail:
		fail.write(url+"\n")

# MAIN

try:
	urls = sys.argv[1] # this is a file
	outfile = sys.argv[2]
	# sleeptime=sys.argv[3]
except:
	print "screener.py path_to_urls outfile sleep(seconds)"

write_html("<html><body>",outfile)

with open(urls,'r') as fopen:
	urls = fopen.readlines()



workding_dir = '/'.join(outfile.split('/')[:-1])
os.chdir(workding_dir)
counter = 1

for url in urls:
	l = len(urls)
	u = url.rstrip()
	print "Processing (%s/%s): %s" % (str(counter),str(l), u)
	capture(u)
	# time.sleep(sleeptime)
	counter += 1

write_html("</body></html>",outfile)

