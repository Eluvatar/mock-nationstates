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
from collections import deque, defaultdict
from ns import id_str

HTML = 'text/html; charset=ISO-8859-1'
XML = 'application/xml; charset=ISO-8859-1'
TEXT = 'text/plain; charset=ISO-8859-1'

BAD_REQUEST = """
<!DOCTYPE html>
<h1 style="color:red">Bad Request</h1>
<p>Sorry, I don't know what you're asking for.
<p style="font-size:small">Error: 400 Bad Request
<p><a href="/pages/api.html">The NationStates API Documentation</a>
"""
if "--ratelimit" in sys.argv:
    ratelimit = True
else:
    ratelimit = False

shards = json.load(open('data/shards.json','r'))

telegrams = json.load(open('data/telegrams.json','r'))

def memmap(fname):
    mm = None
    with open(fname,'r+b') as f:
        mm = mmap.mmap(f.fileno(), 0)
    return mm

def extract(mm,idx,k):
    i,j = idx[k]
    estr = unicode(mm[i:j],'windows-1252').encode('utf-8')
    try:
        return ET.fromstring(estr)
    except PE:
        print "ParseError -- could not parse:"
        print "---begin---"
        print estr
        print "--end---"
        raise

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

def event_time(mm,idx,eid):
    exml = extract(mm,idx,eid)
    return int(exml.find('TIMESTAMP').text)

def event_time_zero(mm,idx):
    eid = min(idx.keys())
    return event_time(mm,idx,eid)

def event_loop_time(mm,idx):
    minid = min(idx.keys())
    maxid = max(idx.keys())
    mints = event_time(mm,idx,minid)
    maxts = event_time(mm,idx,maxid)
    return maxts - mints

base_time = time.time()
event_time_loop_base = event_time_zero(em,events)
event_time_loop_step = event_loop_time(em,events)

def event_timescale(ts):
    elapsed = ts - base_time
    looped = elapsed % event_time_loop_step
    return event_time_loop_base + looped

def outside_timescale(ts):
    elapsed = ts - event_time_loop_base
    now = time.time()
    looped = (now - base_time)%event_time_loop_step
    return int(now - looped + elapsed)

def find_first_event(mm,idx,ts):
    i = min(idx.keys())
    j = max(idx.keys())
    ei,ej = extract(mm,idx,i), extract(mm,idx,j)
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
        ek = extract(mm,idx,k)
        tk = int(ek.find("TIMESTAMP").text)
        if( tk >= ts ):
            return _find_first_event(mm,idx,ts,i,ei,k,ek)
        else:
            return _find_first_event(mm,idx,ts,k,ek,j,ej)
    return _find_first_event(mm,idx,ts,i,ei,j,ej)
    
PORT = 6260

def api_result(key,val,idx,mm,q):
    name = id_str(val)
    if name in idx:
        cherrypy.response.headers['Content-Type']=XML
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
    cherrypy.response.headers['Content-Type']=XML
    root = ET.Element("WORLD")
    if "happenings" in q:
        if "limit" in params:
            limit = min((int(params["limit"]),100))
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
        if not beforeid:
            ts = time.time()
            beforeid = find_first_event(em,events,event_timescale(ts))
        if not sinceid or sinceid < beforeid - limit:
            sinceid = beforeid - limit
        hroot = ET.Element("HAPPENINGS")
        root.append(hroot)
        for eid in xrange(beforeid,sinceid,-1):
            if eid in events:
                e = extract(em,events,eid)
                etsx = e.find("TIMESTAMP")
                ets = int(etsx.text)
                etsx.text = str(outside_timescale(ets))
                hroot.append(e)
    #TODO remove <?xml version='1.0' encoding='windows-1252'?> line
    return ET.tostring(root,'windows-1252')

def action_api_result(params):
    missing_field = """
<!DOCTYPE html>
<h1 style="color:red">Missing field: {0}</h1>
<p style="font-size:small">Error: 400 Bad Request
<p><a href="/pages/api.html">The NationStates API Documentation</a>
"""
    incorrect_secret_key = """
<!DOCTYPE html>
<h1 style="color:red">Incorrect Secret Ke0y</h1>
<p style="font-size:small">Error: 403 Incorrect Secret Key
<p><a href="/pages/api.html">The NationStates API Documentation</a>
"""
    client_not_registered = """
<!DOCTYPE html>
<h1 style="color:red">Client Not Registered For API</h1>
<p style="font-size:small">Error: 403 Client Not Registered For API
<p><a href="/pages/api.html">The NationStates API Documentation</a>
"""
    client_tg_ratelimit_exceeded = """
<!DOCTYPE html>
<h1 style="color:red">API  TG ratelimit exceeded by client "{0}".</h1>
<p style="font-size:small">Error: 429 API  TG ratelimit exceeded by client "{0}".
<p><a href="/pages/api.html">The NationStates API Documentation</a>
"""
    client_recruitment_tg_ratelimit_exceeded = """
<!DOCTYPE html>
<h1 style="color:red">API Recruitment TG ratelimit exceeded by client "{0}".</h1>
<p style="font-size:small">Error: 429 API Recruitment TG ratelimit exceeded by client "{0}".
<p><a href="/pages/api.html">The NationStates API Documentation</a>
"""
    no_such_api_tg = """
<!DOCTYPE html>
<h1 style="color:red">No Such API Telegram Template</h1>
<p style="font-size:small">Error: 400 Bad Request
<p><a href="/pages/api.html">The NationStates API Documentation</a>
"""
    if params['a'] == 'sendTG':
        for param in ('key','tgid','client'):
            if param not in params:
                cherrypy.response.status = 400
                return missing_field.format(param)
        if params['client'] in telegrams['clients']:
            client = telegrams['clients'][params['client']]
            tgs = telegrams['telegrams']
            if 'client' not in params:
                return missing_field.format('client')
            if params['tgid'] in tgs:
                tgid = params['tgid']
                if params['key'] == tgs[tgid]['key']:
                    if ratelimit:
                        last = _last_client_tg[client]
                        ts = time.time()
                        tg = tgs[tgid]
                        if 'recruitment' in tg and tg['recruitment']:
                            if last + 180.0 >= ts:
                                cherrypy.response.status = 429
                                rem = int(last + 181.0 - ts)
                                cherrypy.response.headers['Retry-After'] = rem
                                _msg = client_recruitment_tg_ratelimit_exceeded
                                return _msg.format(client)
                        elif last + 30.0 >= ts:
                            cherrypy.response.status = 429
                            rem = int(last + 31.0 - ts)
                            cherrypy.response.headers['Retry-After'] = rem
                            _msg = client_tg_ratelimit_exceeded
                            return _msg.format(client)
                        _last_client_tg[client] = ts
                    cherrypy.response.headers['Content-Type']=TEXT
                    return "queued"
                else:
                    cherrypy.response.status = 403
                    return incorrect_secret_key
            else:
                cherrypy.response.status = 400
                return no_such_api_tg
        else:
            cherrypy.response.status = 403
            return client_not_registered
    return BAD_REQUEST
    
_last_client_tg = defaultdict(float)

def ratelimit(inner):
    too_many_requests = """
<!DOCTYPE html>
<h1 style="color:red">Too Many Requests From Your IP Address.</h1>
<p>Your IP address {0} has sent more than 50 requests in 30 seconds. Access to the API has been blocked for the next {1} minutes. Please do not send bursts of traffic!</p><p>Requests should be spaced out to avoid hitting the rate limit and compromising server performance. Please ask for assistance in the Technical forum if you are unsure how to do this.
<p style="font-size:small">Error: 429 Too Many Requests
<p><a href="/pages/api.html">The NationStates API Documentation</a>
"""
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
                    return too_many_requests.format(ip, minutes+1)
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
        cherrypy.response.headers['Content-Type'] = HTML 
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
        elif 'a' in params:
            return action_api_result(params)
        else:
            cherrypy.response.status = 400 
            return BAD_REQUEST

if __name__ == "__main__":    
    conf = {'global':{'server.socket_port':PORT}}
    cherrypy.quickstart(MockNationStatesApi(),'/cgi-bin/api.cgi',conf)    
