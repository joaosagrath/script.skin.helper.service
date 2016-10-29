#!/usr/bin/python
# -*- coding: utf-8 -*-

import SimpleHTTPServer, BaseHTTPServer, httplib
import threading
from utils import log_msg, ADDON_ID, log_exception
import xbmc, xbmcvfs
import urlparse

#port is hardcoded as there is no way in Kodi to pass a INFO-label inside a panel,
#otherwise the portnumber could be passed to the skin through a skin setting or window prop
port = 52307

class WebService(threading.Thread):
    event = None
    exit = False
    
    def __init__(self, *args, **kwargs):
        self.artutils = kwargs.get("artutils")
        self.win = kwargs.get("win")
        self.event =  threading.Event()
        threading.Thread.__init__(self, *args)

    def stop(self):
        try:
            log_msg("WebService - stop called",0)
            conn = httplib.HTTPConnection("127.0.0.1:%d" % port)
            conn.request("QUIT", "/")
            conn.getresponse()
            self.exit = True
            self.event.set()
        except Exception as exc:
            log_exception(__name__,exc)

    def run(self):
        log_msg("WebService - start helper webservice on port " + str(port),xbmc.LOGNOTICE)
        try:
            server = StoppableHttpServer(('127.0.0.1', port), StoppableHttpRequestHandler)
            server.serve_forever()
        except Exception as exc:
            log_exception(__name__,exc)

class Request(object):
    # attributes from urlsplit that this class also sets
    uri_attrs = ('scheme', 'netloc', 'path', 'query', 'fragment')

    def __init__(self, uri, headers, rfile=None):
        self.uri = uri
        self.headers = headers
        parsed = urlparse.urlsplit(uri)
        for i, attr in enumerate(self.uri_attrs):
            setattr(self, attr, parsed[i])
        try:
            body_len = int(self.headers.get('Content-length', 0))
        except ValueError:
            body_len = 0
        if body_len and rfile:
            self.body = rfile.read(body_len)
        else:
            self.body = None

class StoppableHttpRequestHandler (SimpleHTTPServer.SimpleHTTPRequestHandler):
    #http request handler with QUIT stopping the server
    raw_requestline = ""

    def __init__(self, request, client_address, server):
        try:
            SimpleHTTPServer.SimpleHTTPRequestHandler.__init__(self, request, client_address, server)
        except Exception as exc:
            log_exception(__name__,exc)

    def do_QUIT (self):
        #send 200 OK response, and set server.stop to True
        self.send_response(200)
        self.end_headers()
        self.server.stop = True

    def log_message(self, format, *args):
        log_msg("Webservice --> %s - - [%s] %s\n" %(self.address_string(),self.log_date_time_string(),format%args))

    def parse_request(self):
        #hack to accept non url encoded strings to pass listitem details from Kodi to webservice
        #strip the passed arguments apart, urlencode them and pass them back as new requestline properly formatted
        if "GET /" in self.raw_requestline or "HEAD /" in self.raw_requestline:
            if self.raw_requestline.startswith("HEAD"): command = "HEAD /"
            else: command = "GET /"
            action = self.raw_requestline.split("&")[0].replace(command,"")
            temp_requestline = self.raw_requestline.replace(command,"").replace(" HTTP/1.1","").replace("\r\n","").replace(action,"")
            old_params = temp_requestline.split("&")
            new_params = {"action": action}
            for param in old_params:
                if param and len(param.split("=")) > 1:
                    key = param.split("=")[0]
                    value = param.split("=")[1]
                    new_params[key] = value
            paramstring = urllib.urlencode(new_params)
            self.raw_requestline = "%s%s&%s HTTP/1.1" %(command,action,paramstring)
        retval = SimpleHTTPServer.SimpleHTTPRequestHandler.parse_request(self)
        self.request = Request(self.path, self.headers, self.rfile)
        return retval

    def do_HEAD(self):
        image = self.send_headers()[0]
        if image:
            image.close()
        return

    def send_headers(self):
        image = None
        preferred_type = None
        org_params = urlparse.parse_qs(self.path)
        params = {}

        for key, value in org_params.iteritems():
            if value:
                value = value[0]
                if "%" in value: value = urllib.unquote(value)
                params[key] = value.decode("utf-8")
        action = params.get("action","")
        title = params.get("title","")
        fallback = params.get("fallback","")
        if fallback.startswith("Default"): fallback = u"special://skin/media/" + fallback

        if action == "getthumb":
            image = self.artutils.google.search_image(title)

        elif action == "getpvrthumb":
            channel = params.get("channel","")
            preferred_type = params.get("type","")
            year = params.get("genre","")
            artwork = self.artutils.get_pvr_artwork(title, channel, genre)
            if preferred_type:
                preferred_types = preferred_type.split(",")
                for preftype in preferred_types:
                    if artwork.get(preftype):
                        image = artwork.get(preftype)
                        break
            else:
                if artwork.get("thumb"): image = artwork.get("thumb")
                if artwork.get("fanart"): image = artwork.get("fanart")
                if artwork.get("landscape"): image = artwork.get("landscape")

        elif action == "getallpvrthumb":
            channel = params.get("channel","")
            images = self.artutils.get_pvr_artwork(title, channel)
            # Ensure no unicode in images...
            for key, value in images.iteritems():
                images[key] = unicode(value).encode('utf-8')
            images = urllib.urlencode(images)
            self.send_response(200)
            self.send_header('Content-type','text/plaintext')
            self.send_header('Content-Length',len(images))
            self.end_headers()
            return images, True

        elif action == "getartwork":
            year = params.get("year","")
            arttype = params.get("type","")
            media_type = params.get("mediatype","")
            imdb_id = params.get("imdbid","")
            artwork = self.artutils.get_extended_artwork(self, imdb_id=imdb_id,title=title,year=year,media_type=media_type)
            jsonstr = json.dumps(artwork)
            self.send_response(200)
            self.send_header('Content-type','application/json')
            self.send_header('Content-Length',len(jsonstr))
            self.end_headers()
            return jsonstr, True

        elif action == "getmusicart":
            preferred_type = params.get("type","")
            artist = params.get("artist","")
            album = params.get("album","")
            track = params.get("track","")
            artwork = self.artutils.get_musicartwork(artist, album, track)
            if preferred_type:
                preferred_types = preferred_type.split(",")
                for preftype in preferred_types:
                    if artwork.get(preftype):
                        image = artwork.get(preftype)
                        break
            else:
                if artwork.get("thumb"): image = artwork.get("thumb")
                if artwork.get("fanart"): image = artwork.get("fanart")

        elif "getmoviegenreimages" in action or "gettvshowgenreimages" in action:
            artwork = {}
            cachestr = "%s-%s" %(action,title)
            cache = self.cache.get(cachestr)
            if cache:
                artwork = cache
            else:
                sort = '"order": "ascending", "method": "sorttitle", "ignorearticle": true'
                if "random" in action:
                    sort = '"order": "descending", "method": "random"'
                    action = action.replace("random","")
                if action == "gettvshowgenreimages":
                    json_result = kodi_json('VideoLibrary.GetTvshows', '{ "sort": { %s }, "filter": {"operator":"is", "field":"genre", "value":"%s"}, "properties": [ "art" ],"limits":{"end":%d} }' %(sort,title,5))
                else:
                    json_result = kodi_json('VideoLibrary.GetMovies', '{ "sort": { %s }, "filter": {"operator":"is", "field":"genre", "value":"%s"}, "properties": [ "art" ],"limits":{"end":%d} }' %(sort,title,5))
                for count, item in enumerate(json_result):
                    artwork["poster.%s" %count] = item["art"].get("poster","")
                    artwork["fanart.%s" %count] = item["art"].get("fanart","")
                self.cache.set(cachestr, artwork)
            if artwork:
                preferred_type = params.get("type","")
                if preferred_type:
                    image = artwork.get(preferred_type,"")
                else:
                    image = artwork.get("poster","")

        #set fallback image if nothing else worked
        if not image and fallback: image = fallback

        if image:
            self.send_response(200)
            if ".jpg" in image: self.send_header('Content-type','image/jpg')
            elif image.lower().endswith(".gif"): self.send_header('Content-type','image/gif')
            else: self.send_header('Content-type','image/png')
            log_msg("found image for request %s  --> %s" %(try_encode(self.path),try_encode(image)))
            st = xbmcvfs.Stat(image)
            modified = st.st_mtime()
            self.send_header('Last-Modified',"%s" %modified)
            image = xbmcvfs.File(image)
            size = image.size()
            self.send_header('Content-Length',str(size))
            self.end_headers()
        else:
            self.send_error(404)
        return image, None

    def do_GET(self):
        result, multi = self.send_headers()
        if result and not multi:
            #send the image to the client
            log_msg("WebService -- sending image for --> " + try_encode(self.path))
            self.wfile.write(result.readBytes())
            result.close()
        elif result:
            #send multiple images to the client (plaintext)
            log_msg("WebService -- sending multiple images or json for --> " + try_encode(self.path))
            self.wfile.write(result)
        return

class StoppableHttpServer (BaseHTTPServer.HTTPServer):
    """http server that reacts to self.stop flag"""

    def serve_forever (self):
        """Handle one request at a time until stopped."""
        self.stop = False
        while not self.stop:
            self.handle_request()


def stop_server (port):
    """send QUIT request to http server running on localhost:<port>"""
    conn = httplib.HTTPConnection("localhost:%d" % port)
    conn.request("QUIT", "/")
    conn.getresponse()
