import templates

import logging
import traceback
import configparser

import http.server
import urllib
import ssl
import requests

import os
import sys
import time
import tempfile

import queue
import threading
import subprocess

from cairosvg import svg2png

class DymoLinux:
    def __init__(self):
        if len(sys.argv) > 1:
            location = sys.argv[1]
            try: os.stat(location)
            except FileNotFountError:
                print('Cannot open config file {}'.format(location))
                quit()

        else:
            for location in ('dymo-linux.ini', '/etc/dymo-linux.ini',
                             '~/.config/dymo-linux.ini'):
                try: os.stat(location)
                except FileNotFoundError:
                    location = None
                    continue
                else: break
        
            if not location:
                print("Cannot find config file. Please specify the file's location or place it in a supported location.")
                quit()
        
        self.config = configparser.ConfigParser()
        self.config.read(location)
        
        self.dpi = self.config.getint('DymoLinux', 'dpi')
        self.printer = self.config.get('DymoLinux', 'printer', fallback = None)
        self.debug = self.config.getboolean('DymoLinux', 'debug', fallback = False)
        self.fakeprint = self.config.getboolean('DymoLinux', 'fakeprint', fallback = False)

        self.sslcert = self.config.get('DymoLinux', 'sslcert')
        self.sslkey = self.config.get('DymoLinux', 'sslkey')

        if self.debug: logging.basicConfig(level = logging.DEBUG)
        else: logging.basicConfig(level = logging.INFO)
        
        self.labels = []
        for section in self.config.sections():
            if section.startswith('Label'):
                self.labels.append({
                    'svgfile': self.config.get(section, 'svgfile'),
                    'hasfield': self.config.get(section, 'hasfield', fallback = None)
                })
        
        if len(self.labels) == 0:
            print('Config file must contain at least one [Label] section')
            quit()
        
        self.jobqueue = queue.Queue()
        self.jobthread = None
        
        self.job_counter = 1
        self.print_counter = 1

    def print_label(self, pdf_url):

        jobnum = self.job_counter
        self.job_counter += 1
        
        thread = threading.Thread(target = self.download_pdf, args = (pdf_url, jobnum))
        thread.start()

    # Downloads a PDF and adds to the internal print queue
    def download_pdf(self, pdf_url, jobnum):
        logging.debug('Processing job #{}'.format(jobnum))
        
        print('pdf_url = #{}'.format(pdf_url[0]))

        outfilename = os.path.join(tempfile.gettempdir(), 'dymo-label-{}.pdf'.format(jobnum))

        logging.debug('pdf_url = #{}'.format(pdf_url))	
        r = requests.get(pdf_url[0], allow_redirects=True)
        open(outfilename, 'wb').write(r.content)
        
        self.add_job(outfilename)
        logging.debug('Rendered job #{}'.format(jobnum))

    def add_job(self, filename):
        self.jobqueue.put(filename)
        
        if not self.jobthread or not self.jobthread.is_alive():
            self.jobthread = threading.Thread(target = self.do_jobthread)
            self.jobthread.start()
        
    def do_jobthread(self):
        # Waits a bit to aggregate multiple labels into one job, useful for certain printers since for some reason our DYMOs like to disconnect and reconnect USB after each job. Bleh.
        time.sleep(1)
        
        files = []
        while True:
            try: files.append(self.jobqueue.get(block = False))
            except queue.Empty: break
        
        if self.printer: printsettings = ('-P', self.printer)
        else: printsettings = tuple()
        
        logging.debug('Aggregating {} jobs into single print'.format(len(files)))
        
        if self.fakeprint:
            logging.debug('Fakeprint enabled, not really printing print job #{}'.format(self.print_counter))
        else:
            subprocess.run(
                ('lpr', '-r', '-T', 'Dymo Web Service Clone #{}'.format(self.print_counter)) +
                printsettings + tuple(files)
            )
        
        logging.debug('Printed job #{}'.format(self.print_counter))
        self.print_counter += 1

    def get_printer_info_xml(self):
        # Currently uses placeholder data. Real printer data could be pulled from CUPS if needed.
        return '<Printers>{}</Printers>'.format(
            templates.printer_info_template.format(
                name = 'Dymo Web Service Clone',
                modelname = 'Dymo Web Service Clone',
                isconnected = 'True',
                islocal = 'True',
                istwinturbo = 'False'
            )
        )

dymo = DymoLinux()

class DymoRequestHandler(http.server.BaseHTTPRequestHandler):
    def respond_with_data(self, data, content_type = 'text/html', code = 200):
        self.send_response(code)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Charset', 'utf-8')
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'max-age=0')
        self.end_headers()
        
        if type(data) == str:
            self.wfile.write(data.encode('utf-8'))
        else:
            self.wfile.write(data)
        
    def do_GET(self):
        try:
            self.do_GET_wrapped()
        except:
            tb = traceback.format_exc()
            logging.error(tb)
            if dymo.debug:
                self.respond_with_data(templates.exception_traceback_template.format(tb.replace('\n', '<br>')), code = 500)
            else:
                self.respond_with_data(templates.exception_template, code = 500)                
    
    def do_GET_wrapped(self):
        logging.debug('GET {} from {}'.format(self.path, self.client_address[0]))

        if self.path == '/' or self.path == '/DYMO/DLS/Printing/Check':
            self.respond_with_data(templates.status_template)
        
        elif self.path == '/DYMO/DLS/Printing/StatusConnected':
            # TODO determine under what circumstances this should return 'false'
            self.respond_with_data('true', content_type = 'text/plain')
        
        elif self.path == '/DYMO/DLS/Printing/GetPrinters':
            self.respond_with_data(dymo.get_printer_info_xml(), content_type = 'text/xml')
        
        else:
            self.respond_with_data(templates.error_404_template, code = 404)

    def do_POST(self):
        try:
            self.do_POST_wrapped()
        except ssl.SSLEOFError:
            # The SSL module doesn't like the way Blink / WebKit end HTTPS connections. Ignoring.
            pass
        except:
            tb = traceback.format_exc()
            logging.error(tb)
            if dymo.debug:
                self.respond_with_data(templates.exception_traceback_template.format(tb.replace('\n', '<br>')), code = 500)
            else:
                self.respond_with_data(templates.exception_template, code = 500)              
                
    def do_POST_wrapped(self):
        logging.debug('POST {} from {}'.format(self.path, self.client_address[0]))
        
        if self.path == '/DYMO/DLS/Printing/PrintLabel':
            logging.info('New print job from {}'.format(self.headers.get('Referer') or '<unknown>'))

            length = int(self.headers['Content-Length'])
            postdata = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8'))
            
            dymo.print_label(postdata['pdfUrl'])

            self.respond_with_data('')

        else:
            self.respond_with_data(templates.error_404_template, code = 404)

if __name__ == '__main__':
    for port in range(41951, 41961):
        try:
            httpd = http.server.HTTPServer(('127.0.0.1', port), DymoRequestHandler)
        except OSError:
            continue
        else:
            break
    
    logging.info('Serving on port {}'.format(port))
    
    # TODO something about this causes wget to throw errors when accessing. Works OK in Firefox, so not fixing for now.
    httpd.socket = ssl.wrap_socket(httpd.socket, certfile = dymo.sslcert, keyfile = dymo.sslkey, server_side = True)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('Bye!')
