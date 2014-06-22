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
from xml.etree.ElementTree import ParseError as PE
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
em = memmap('data/happenings.xml')

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

def event_scan(mm,idx):
    beg = "<EVENT"
    end = "</EVENT>"
    done = False
    i = mm.find(beg)
    while not done:
        j = mm.find(beg, i+len(beg))
        if( j == -1 ):
            done = True
        eidi = i+len('<EVENT id="')
        eidj = mm.find('"',eidi)
        eid = int(mm[eidi:eidj])
        idx[eid] = (i,mm.find(end,i+len(beg))+len(end))
        i=j

events = dict()
event_scan(em, events)

def event_time_adjust(mm,idx,ts):
    eid = min(idx.keys())
    i,j = idx[eid]
    try:
        exml = ET.fromstring(mm[i:j])
    except PE:
        print mm[i:j]
        raise
    ets = int(exml.find('TIMESTAMP').text)
    return int(ts-ets)

event_time_shift = event_time_adjust(em,events,time.time())

def find_first_event(mm,idx,ts):
    i = min(idx.keys())
    j = max(idx.keys())
    ii,ij = idx[i]
    ji,jj = idx[j]
    ei,ej = ET.fromstring(mm[ii:ij]), ET.fromstring(mm[ji:jj])
    def _find_first_event(mm,idx,ts,i,ei,j,ej):
        if( i == j ):
            return i
        k = int((i+j)/2)
        while k not in idx:
            k += 1
        if( k == j ):
            k = int((i+j)/2)
            while k not in idx:
                k -= 1
        if( i == k ):
            return j
        ki,kj = idx[k]
        ek = ET.fromstring(mm[ki:kj])
        tk = int(ek.find("TIMESTAMP").text)
        if( tk >= ts ):
            return _find_first_event(mm,idx,ts,i,ei,k,ek)
        else:
            return _find_first_event(mm,idx,ts,k,ek,j,ej)
    return _find_first_event(mm,idx,ts,i,ei,j,ej)
    
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


def world_api_result(nm,nations,rm,regions,em,events,q,params):
    cherrypy.response.headers['Content-Type']='application/xml'
    root = ET.Element("WORLD")
    if "happenings" in q:
        if "limit" in params:
            limit = int(params["limit"])
        else:
            limit = 100
        if "sinceid" in params:
            sinceid = int(params["sinceid"])
        else:
            sinceid = None
        if "beforeid" in params:
            beforeid = int(params["beforeid"])
        else:
            beforeid = None
        if not (beforeid or sinceid):
            ts = time.time()
            sinceid = find_first_event(em,events,ts-event_time_shift)
        if not sinceid:
            sinceid = beforeid - limit
        if not beforeid:
            beforeid = sinceid + limit
        hroot = ET.Element("HAPPENINGS")
        root.append(hroot)
        for eid in xrange(sinceid,beforeid):
            if eid in events:
                i,j = events[eid]
                e = ET.fromstring(em[i:j])
                etsx = e.find("TIMESTAMP")
                ets = int(etsx.text)
                etsx.text = str(ets+event_time_shift)
                hroot.append(e)
    return ET.tostring(root)

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
        elif q:
            return world_api_result(nm,nations,rm,regions,em,events,q,params)
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
