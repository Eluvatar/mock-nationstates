#!/usr/bin/python2.7

#   Copyright 2014 Eluvatar
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json, mmap, cherrypy
import xml.etree.ElementTree as ET
import time, sys
from collections import deque
from ns import id_str

if "--ratelimit" in sys.argv:
    ratelimit = True
else:
    ratelimit = False

shards = json.load(open('data/shards.json','r'))

def memmap(fname):
    mm = None
    with open(fname,'r+b') as f:
        mm = mmap.mmap(f.fileno(), 0)
    return mm

nm = memmap('data/nations.xml')
rm = memmap('data/regions.xml')

def scan(mm,beg,end,idx):
    done = False
    i = mm.find(beg)
    while not done:
        j = mm.find(beg, i+len(beg))
        if( j == -1 ):
            j = mm.find(end,i+len(beg))
            done = True
        namei = mm.find("<NAME>",i)+len("<NAME>")
        namej = mm.find("</NAME>",namei)
        name = mm[namei:namej]
        idx[id_str(name)] = (i,j)
        i=j

nations = dict()
scan(nm, "<NATION>", "</NATIONS>", nations)

regions = dict()
scan(rm, "<REGION>", "</REGIONS>", regions)

PORT = 6260

def api_result(key,val,idx,mm,q):
    name = id_str(val)
    if name in nations:
        cherrypy.response.headers['Content-Type']='application/xml'
        i,j = idx[name]
        if( q == None ):
            return mm[i:j]
        else:
            src = ET.fromstring(mm[i:j])
            root = ET.Element(src.tag)
            for shard in q:
                if shard in shards[key]:
                    root.append(src.find(shards[key][shard]))
            return ET.tostring(root)
    else:
        cherrypy.response.status = 404
        return """
<!DOCTYPE html>
<h1 style="color:red">Unknown {0}: "{1}".</h1>
<p style="font-size:small">Error: 404 Not Found
<p><a href="/pages/api.html">The NationStates API Documentation</a>
""".format(key,val)

def ratelimit(inner):
    if ratelimit:
        last = deque()
        violation = [0.0]
        def __outer(*args, **kwargs):
            ts = time.time()
            last.append(ts)
            if( len(last) > 50 ):
                rel = last.popleft()
                if( violation[0] + (15*60.0) > ts or rel >= ts - 30.0 ):
                    if( rel >= ts - 30.0 ):
                        violation[0] = ts
                        cherrypy.request.app.log.error( \
                          "ratelimit violation at {0}".format(ts))
                    cherrypy.response.status = 429
                    ip = cherrypy.request.remote.ip
                    minutes = int((violation[0]+(15*60.0) - ts)/60)
                    return """
<!DOCTYPE html>
<h1 style="color:red">Too Many Requests From Your IP Address.</h1>
<p>Your IP address {0} has sent more than 50 requests in 30 seconds. Access to the API has been blocked for the next {1} minutes. Please do not send bursts of traffic!</p><p>Requests should be spaced out to avoid hitting the rate limit and compromising server performance. Please ask for assistance in the Technical forum if you are unsure how to do this.
<p style="font-size:small">Error: 429 Too Many Requests
<p><a href="/pages/api.html">The NationStates API Documentation</a>
""".format(ip, minutes+1)
            return inner(*args, **kwargs)
    else:
        def __outer(*args, **kwargs):
            return inner(*args, **kwargs)
    return __outer

class MockNationStatesApi(object):
    exposed = True
    
    @cherrypy.expose
    @ratelimit
    def default(self, *args, **params):
        for pair in args:
            key, val = pair.split("=",1)
            params[key] = val
        if 'q' in params:
            q = params['q'].replace('+',' ').split()
        else:
            q = None
        if 'nation' in params:
            return api_result('nation',params['nation'],nations,nm,q)
        elif 'region' in params:
            return api_result('region',params['region'],regions,rm,q)
        else:
            cherrypy.response.status = 400         
            return """
<!DOCTYPE html>
<h1 style="color:red">Bad Request</h1>
<p>Sorry, I don't know what you're asking for.
<p style="font-size:small">Error: 400 Bad Request
<p><a href="/pages/api.html">The NationStates API Documentation</a>
"""

    
conf = {'global':{'server.socket_port':PORT}}
cherrypy.quickstart(MockNationStatesApi(),'/cgi-bin/api.cgi',conf)    
