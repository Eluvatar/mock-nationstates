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
import time, sys, os
from collections import deque, defaultdict
import random, string, re
from copy import copy
from ns import id_str

HTML = 'text/html; charset=utf-8'
XML  = 'application/xml; charset=ISO-8859-1'
TEXT = 'text/plain; charset=ISO-8859-1'

NOT_FOUND = """
<h2>Page Not Found</h2>
<p>What you seek is not here.<br><br>
"""
#Note: in reality the 404 page includes the overall NS template. Not bothering.

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

if "--readonly" in sys.argv:
    readonly = True
else:
    readonly = False

shards = json.load(open('data/shards.json','r'))

logins = json.load(open('data/nations.json','r'))
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

NFILE = 'data/nations.xml'
RFILE = 'data/regions.xml'

nm = memmap(NFILE)
rm = memmap(RFILE)
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
        if "sinceid" in params and params["sinceid"] != '':
            sinceid = int(params["sinceid"])
        else:
            sinceid = None
        if "beforeid" in params and params["beforeid"] != '':
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

def api_ratelimit(inner):
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
        def _outer(*args, **kwargs):
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
        def _outer(*args, **kwargs):
            return inner(*args, **kwargs)
    return _outer

def site_ratelimit(inner):
    too_many_requests = "Your script is breaking the non-api rate limit!"
    if ratelimit:
        last = deque()
        def _outer(*args, **kwargs):
            ts = time.time()
            last.append(ts)
            if( len(last) > 10 ):
                rel = last.popleft()
                if( rel >= ts - 60.0 ):
                    cherrypy.request.app.log.error( \
                      "rules violation at {0}".format(ts))
                    cherrypy.response.status = 429
                    return too_many_requests
            return inner(*args, **kwargs)
        return _outer
    else:
        return inner

class MockNationStatesApi(object):
    exposed = True
    
    @cherrypy.expose
    @api_ratelimit
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

def _chk():
    seq=(string.ascii_letters+string.digits)
    r = map(lambda i: random.choice(seq), range(0,11))
    return "JG"+"".join(r)

def _key():
    seq=string.hexdigits[:16]
    r = map(lambda i: random.choice(seq), range(0,12))
    return "".join(r)

def _token_key():
    seq=string.ascii_letters+string.digits
    r = map(lambda i: random.choice(seq), range(0,22))
    return "".join(r)

def _find_arg(args, expr):
    regex = re.compile(expr)
    for a in args:
        if regex.match(a):
            return a
    return None

def _redir_slash():
    cherrypy.response.status = 302
    cherrypy.response.headers['Location'] = "/"
    return ""

class MockNationStatesSite(object):
    exposed = True

    def __init__(self):
        self.sessions=dict()

    @site_ratelimit
    def GET(self, *args, **params):
        normal = """
<form action="/" method="post" target="_top"><input type="hidden" name="logging_in" value="1"><p>NATION
<p><input size="18" name="nation" onClick="document.getElementById('loginbox').className = 'activeloginbox';">
<p>PASSWORD
<p><input size="18" name="password" type="password">
<p><label><input type="checkbox" name="autologin" value="yes"> Remember me</label>
<p><input type="submit" value="Login" name="submit"></form>
        """
        if 'pin' in cherrypy.request.cookie:
            pin = int(cherrypy.request.cookie['pin'].value)
            if pin in self.sessions:
                if 'logout' in params and params['logout']:
                    del self.sessions[pin]
                    return normal
                sess = self.sessions[pin]
#                return "args=%s<br>params=%s<br>sess=%s"%(args,params,sess)
            else:
                return normal
        else:
            return normal
        if 'page=compose_telegram' in args:
            region = logins[sess['nation']]['region']
            return """
<!-- compose_telegram_template -->
<div id="tgcompose" class="tgreply" >
<form method="post" action="page=telegrams">
<input type="hidden" name="chk" value="%(chk)s">
<fieldset class="hide rmbpreview preview"><legend>Preview</legend>
<div class="previewcontent"></div>
</fieldset>

<div class="widebox">

<div id="tgto">
<div id="tgto-left"><p>To: </div>
<div id="tgto-right">
<input type="text" name="tgto" id="entity_name" size="28" value="">
<span class="tgtoadvanced"><a href="#advanced" title="Advanced Options">&#x25BC;</a></span>
<div id="tgtoloaded"></div>
</div>
</div>
<div class="rmbspacer"></div>

<div id="tgadvanced" class="hide">
<p class="tgadvancedadd">Add:
<a href="#nation" class="tgaddnation">Nation</a> &bull;
<a href="#region" class="tgaddregion">Region</a> &bull;
<a href="#special" class="tgaddtag">Special</a> 
<a href="" class="ttq" id="ttq_1">[?]</a>
<select id="tgaddnationselector" class="slim hide"><option value="" selected="selected">From Your Dossier:</option>
<optgroup label="-----------------------">

</optgroup>
</select>
<select id="tgaddregionselector" class="slim hide"><option value="" selected="selected">From Your Region Dossier:</option>
<option>%(region)s</option>
<option value="" disabled>&mdash;</option>

</select>
<select id="tgaddtagselector" class="slim hide"><option value="" selected="selected">Add Special Group:</option>
<option value="delegates">World Assembly Delegates</option>
<option value="WA">World Assembly Members</option>
<option value="all">All</option>
<option value="new100">New (100)</option>
<option value="new500">New (500)</option>
<option value="new2500">New (2,500)</option>
<option value="refounded100">Refounded (100)</option>
<option value="refounded500">Refounded (500)</option>
<option value="refounded2500">Refounded (2,500)</option>
<option value="ejected100">Ejected (100)</option>
<option value="ejected500">Ejected (500)</option>
<option value="ejected2500">Ejected (2,500)</option>
<option value="newdelegates100">New WA Delegates (100)</option>
<option value="welcome">Welcome to Region</option>
</select>
<p id="ttq_1a" class="tooltip">Telegrams can be addressed to individual nations,
to all nations within a particular region, or to special groups
of nations, such as all current <strong>World Assembly Delegates</strong>, all
<strong>World Assembly Members</strong>, or nations of a particular type:<br><br>
<strong>New (#)</strong>: Nations receive your telegram shortly after being created.<br><br>
<strong>Refounded (#)</strong>: Nations receive your telegram after returning to the world
following ceasing to exist.<br><br>
<strong>Ejected (#)</strong>: Nations that are ejected from a region by the Founder or
Delegate into the <a href="/region=the_rejected_realms">the Rejected Realms</a>.
Bunch of troublemakers and malcontents, the lot of them.<br><br>
<strong>New Delegates (#)</strong>: Nations receive your telegram after being elected
WA Delegate of their region.<br><br>
For these, you specify how many copies of your telegram you want delivered. You can then track
how many copies have been delivered so far (and to whom), and how many remain.<br><br>
Founders and Delegates may also compose a <strong>Welcome</strong> Telegram that is
delivered to new arrivals in their region. (See your
<a href="/page=region_control#communication">Region Control</a>.)<br><br>

<p id="tgrecruitbox"><label><input type="checkbox" name="is_recruitment_tg" id="is_recruitment_tg"
> This is a </label>
<select name="recruittype" id="recruittype" class="slim" 
disabled>
<option value="recruit" >recruitment</option>
<option value="campaign" >campaign</option></select>
<label for="is_recruitment_tg"> telegram</label><span id="recruitregionname" class="hide">
<label for="is_recruitment_tg"> for </label>
<select name="recruitregion" id="recruitregion" class="slim">
<option value="region">%(region)s</option>
<option value="org">an organization</option>
</select></span>.
<input type="hidden" name="recruitregionrealname" value="%(region)s">
<a href="" class="ttq" id="ttq_2">[?]</a>
<p id="ttq_2a" class="tooltip" style="margin-top:16px;">You must mark telegrams that:
<br><br>
<strong>Recruit</strong>: encourage nations to move regions or join an organization
<br><br>
<strong>Campaign</strong>: encourage voting on a World Assembly resolution or proposal
<br><br>
Send a lot of these? <a href="/page=faq#telegrams">More info.</a></p>
</div>
<textarea name="message" wrap="soft"></textarea></div>
<p class="nscodedesc">Formatting tags:
<abbr title="Bold text: e.g. I [b]love[/b] your nation!">[b]</abbr>
<abbr title="Underline text: e.g. I [u]really[/u] love your nation!">[u]</abbr>
<abbr title="Italicize text: e.g. I [i]cannot express how much[/i] I love your nation!">[i]</abbr>
<abbr title="Nation link: e.g. We must form an alliance against [nation]Testlandia[/nation]!">[nation]</abbr>
<abbr title="Region link: e.g. The infiltrators appear to be coming from [region]Lazarus[/region].">[region]</abbr>
<a href="/page=faq#nscode" target="_blank" style="font-weight:bold; color:#999999">Help</a>
<p class="tgsendreplybuttons"><button type="submit" name="send" value="1" class="sendtgbutton button icon approve primary">Send</button>
<button type="submit" class="previewbutton tgpreviewbutton button search icon">Preview</button>
</form>
</div>
<!-- end compose_telegram_template -->
                   """ % dict(chk=sess['chk'],region=region)
        if 'page=tg' in args:
            if 'raw=1' in args:
                a = _find_arg(args, '^tgid=')
                if a:
                    tgid=a.split('=')[1]
                    tg = copy(telegrams['telegrams'][tgid])
                    tg["id"]=tgid
                    tg["nation"]=sess['nation']
                    tg["title"]=sess['nation']
                    tg['flag']='/images/flags/Default.png'
                    if 'token_key' in tg:
                        return u"""
<div id="tgid-{id}" class="tg"><div class="tgtopline toplinetgcat-4"><img src="/images/tgcat-4.png" class="tgcaticon" title="External telegram"><div class="tg_headers"><a href="nation={nation}" class="nlink"><img src="{flag}" class="smallflag" alt="" title="{title}"><span>{title}</span></a> \u2192 <strong>tag:</strong> api</div><div class="tgsample">

NATION =  %NATION% 
TOKEN =  %TOKEN% 
  Token Secret Key: {token_key}</div><div class="tgdateline"><a href="/page=tg/tgid={id}" class="tgsentline">some time ago</a></div><div class="rmbspacer"></div></div><div class="tgmsg"><div class="tgcontent tgmsg-mass tgmsg-cat tgcontentstriped"><div class="tgstripe" style="background-image:url({flag});"></div><p></p><pre>

NATION = <span class="tgtoken">%NATION%</span>
TOKEN = <span class="tgtoken">%TOKEN%</span>
</pre><p class="tgstatusline">Token Secret Key: {token_key}<p class="replyline"><a href="#deliverydetails" class="masstgreport">Delivery Reports</a><div class="rmbspacer"></div></div></div></div>
                        """.format(**tg)
                    else:
                        return u"""
<div id="tgid-{id}" class="tg"><div class="tgtopline toplinetgcat-4"><img src="/images/tgcat-4.png" class="tgcaticon" title="External telegram"><div class="tg_headers"><a href="nation={nation}" class="nlink"><img src="{flag}" class="smallflag" alt="" title="{title}"><span>{title}</span></a> \u2192 <strong>tag:</strong> api</div><div class="tgsample">

NATION =  %NATION% 
</div><div class="tgdateline"><a href="/page=tg/tgid={id}" class="tgsentline">some time ago</a></div><div class="rmbspacer"></div></div><div class="tgmsg"><div class="tgcontent tgmsg-mass tgmsg-cat tgcontentstriped"><div class="tgstripe" style="background-image:url({flag});"></div><p></p><pre>

NATION = <span class="tgtoken">%NATION%</span>
</pre><p class="replyline"><a href="#deliverydetails" class="masstgreport">Delivery Reports</a><div class="rmbspacer"></div></div></div></div>
                        """.format(**tg)


    @site_ratelimit
    def POST(self, *args, **params):
        if 'logging_in' in params and params['logging_in']:
            if 'nation' in params and 'password' in params:
                nat = id_str(params['nation'])
                if nat in logins:
                    if logins[nat]['password'] == params['password']:
                        cherrypy.response.status = 302
                        if 'target' in params:
                            cherrypy.response.headers['Location'] = "/page=%s"%target
                        else:
                            cherrypy.response.headers['Location'] = "/nation=%s"%nat
                        pin = random.randint(100000,100000000000)
                        cherrypy.response.cookie['pin']=pin
                        self.sessions[pin]={'nation':nat,'chk':_chk()}
                    else:
                        return '<p class="error">Incorrect password. Please try again.</p>'
                else:
                   return "invalid nation!"
            else:
                return "Must log in to something!"
        if 'pin' in cherrypy.request.cookie:
            pin = int(cherrypy.request.cookie['pin'].value)
            if pin in self.sessions:
                sess = self.sessions[pin]
            else:
                return _redir_slash()
        else:
            return _redir_slash()
        if 'page=telegrams' in args:
            if 'chk' in params and 'tgto' in params and 'message' in params and 'send' in params:
                if params['tgto'] == 'tag:api':
                    if params['chk'] != sess['chk']:
                        return """
<p class="error">This request failed a security check. Please try again.</p>
                        """
                    tg = dict(key=_key())
                    if '%TOKEN%' in params['message']:
                        tg['token_key']=_token_key()
                    tgid=str(1+max(map(int,telegrams["telegrams"].keys())))
                    telegrams["telegrams"][tgid]=tg
                    if not readonly:
                        json.dump(telegrams,open('data/telegrams.json','w+'))
                    return """
<p class="info">Your API template has been created! <a href="/page=tg/tgid={tgid}">View Template</a><br><br>To wire a copy to a nation, make an API request to:<br><br><b><a href="http://www.nationstates.net/cgi-bin/api.cgi?a=sendTG&amp;client=YOUR_API_CLIENT_KEY&amp;tgid={tgid}&amp;key={key}&amp;to=NATION_NAME">http://www.nationstates.net/cgi-bin/api.cgi?a=sendTG&amp;client=YOUR_API_CLIENT_KEY&amp;tgid={tgid}&amp;key={key}&amp;to=NATION_NAME</a></b><br><br>... replacing "NATION_NAME" with the name of a recipient. You can test this now by sending it to yourself.<br><br><b>Do not share this URL or your Secret Key with anyone!</b><br><br>This code will remain available for your reference under the telegram's <em>Delivery Reports</em>.<br><br><b>Recruiters/Campaigners:</b> This telegram's category is now set and cannot be changed. Did you set it correctly? <a href="/page=tg/tgid={tgid}">Check now</a> to avoid modly wrath!</p>
                    """.format(tgid=tgid,key=tg["key"])
                else:
                    cherrypy.response.status=501
                    return "Only api template creation mocked out!"
                   

if __name__ == "__main__":    
    conf = {
        'global': {
            'server.socket_port':PORT,
        },
    }
    staticconf = { 
        'global': {
            'server.socket_port':PORT,
        },
        '/': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
        },
        '/pages': {
            'tools.staticdir.root' : os.path.abspath(os.getcwd()),
            'tools.staticdir.on': True,
            'tools.staticdir.dir' : './pages'
        }
    }
    cherrypy.config.update(conf)
    cherrypy.tree.mount(MockNationStatesApi(),'/cgi-bin/api.cgi',conf)
    cherrypy.tree.mount(MockNationStatesSite(),'/',staticconf)
    cherrypy.engine.start()
    cherrypy.engine.block()
