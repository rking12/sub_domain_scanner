from typing import Tuple

version = "V0.03"
build = "003"
import json
import os
import random
import re
import ssl
import time
from datetime import datetime
from threading import Thread

import dns.resolver

try:
    import urllib.request as urllib2
except ImportError:
    import urllib2

try:
    import queue
except:
    import Queue as queue
txt = ''


# exit handler for signals.  So ctrl+c will work,  even with py threads.
def killme(signum=0, frame=0):
    os.kill(os.getpid(), 9)


class lookup(Thread):

    def __init__(self, in_q, out_q, domain, wildcard=False, resolver_list=[]):
        Thread.__init__(self)
        self.in_q = in_q
        self.out_q = out_q
        self.domain = domain
        self.wildcard = wildcard
        self.resolver_list = resolver_list
        self.resolver = dns.resolver.Resolver()
        if len(self.resolver.nameservers):
            self.backup_resolver = self.resolver.nameservers
        else:
            # we must have a resolver,  and this is the default resolver on my system...
            self.backup_resolver = ['127.0.0.1']
        if len(self.resolver_list):
            self.resolver.nameservers = self.resolver_list

    def check(self, host):
        slept = 0
        while True:
            try:
                answer = self.resolver.query(host)
                if answer:
                    return str(answer[0])
                else:
                    return False
            except Exception as e:
                if type(e) == dns.resolver.NXDOMAIN:
                    # not found
                    return False
                elif type(e) == dns.resolver.NoAnswer or type(e) == dns.resolver.Timeout:
                    if slept == 4:
                        # This dns server stopped responding.
                        # We could be hitting a rate limit.
                        if self.resolver.nameservers == self.backup_resolver:
                            # if we are already using the backup_resolver use the resolver_list
                            self.resolver.nameservers = self.resolver_list
                        else:
                            # fall back on the system's dns name server
                            self.resolver.nameservers = self.backup_resolver
                    elif slept > 5:
                        # hmm the backup resolver didn't work,
                        # so lets go back to the resolver_list provided.
                        # If the self.backup_resolver list did work, lets stick with it.
                        self.resolver.nameservers = self.resolver_list
                        # I don't think we are ever guaranteed a response for a given name.
                        return False
                    # Hmm,  we might have hit a rate limit on a resolver.
                    time.sleep(1)
                    slept += 1
                    # retry...
                elif type(e) == IndexError:
                    # Some old versions of dnspython throw this error,
                    # doesn't seem to affect the results,  and it was fixed in later versions.
                    pass
                else:
                    # dnspython threw some strange exception...
                    raise e

    def run(self):
        while True:
            sub = self.in_q.get()
            if sub != False:
                print('Try: %s' % (sub))

            if not sub:
                # Perpetuate the terminator for all threads to see
                self.in_q.put(False)
                # Notify the parent of our death of natural causes.
                self.out_q.put(False)
                break
            else:
                try:
                    test = "%s.%s" % (sub, self.domain)
                    addr = self.check(test)
                    if addr and addr != self.wildcard:
                        test = (test, str(addr))
                        self.out_q.put(test)
                except Exception as ex:
                    # do nothing
                    nothing = True


# ++ FUNCTIONS //#

# func Writelog
def func_writelog(how, logloc, txt):  # how: a=append, w=new write
    with open(logloc, how) as mylog:
        mylog.write(txt)


# Return a list of unique sub domains,  alfab. sorted .
def extract_subdomains(file_name):
    subs = {}
    sub_file = open(file_name).read()
    # Only match domains that have 3 or more sections subdomain.domain.tld
    domain_match = re.compile("([a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*)+")
    f_all = re.findall(domain_match, sub_file)
    del sub_file
    for i in f_all:
        if i.find(".") >= 0:
            p = i.split(".")[0:-1]
            # gobble everything that might be a TLD
            while p and len(p[-1]) <= 3:
                p = p[0:-1]
            # remove the domain name
            p = p[0:-1]
            # do we have a subdomain.domain left?
            if len(p) >= 1:
                # print(str(p) + " : " + i)
                for q in p:
                    if q:
                        # domain names can only be lower case.
                        q = q.lower()
                        if q in subs:
                            subs[q] += 1
                        else:
                            subs[q] = 1
    # Free some memory before the sort...
    del f_all
    # Sort by freq in desc order
    subs_sorted = sorted(subs.keys(), key=lambda x: subs[x], reverse=True)
    return subs_sorted


def check_resolvers(file_name, threads):
    txt = 'Checking Resolvers...'
    print(txt)
    ret = []
    resolver = dns.resolver.Resolver()
    res_file = open(file_name).read()
    for server in res_file.split("\n"):
        server = server.strip()
        if server:
            resolver.nameservers = [server]
            try:
                resolver.query("www.google.com")
                # should throw an exception before this line.
                ret.append(server)
            except:
                pass
    return ret


def run_target(target, hosts, resolve_list, thread_count, print_numeric, threads, time_stamp_start, logloc):
    # The target might have a wildcard dns record...
    wildcard = False
    try:

        resp = dns.resolver.Resolver().query(
            "would-never-be-a-fucking-domain-name-" + str(random.randint(1, 9999)) + "." + target)
        wildcard = str(resp[0])
    except:
        pass
    in_q = queue.Queue()
    out_q = queue.Queue()
    for h in hosts:
        in_q.put(h)
    # Terminate the queue
    in_q.put(False)
    step_size = int(len(resolve_list) / thread_count)
    # Split up the resolver list between the threads.
    if step_size <= 0:
        step_size = 1
    step = 0
    for i in range(thread_count):
        threads.append(lookup(in_q, out_q, target, wildcard, resolve_list[step:step + step_size]))
        threads[-1].start()
    step += step_size
    if step >= len(resolve_list):
        step = 0

    threads_remaining = thread_count
    subdlist = {}
    subiplist = {}
    i = 0
    while True:
        try:
            d = out_q.get(True, 10)
            # we will get an empty exception before this runs.
            if not d:
                threads_remaining -= 1
            else:
                if not print_numeric:
                    txt = "%s" % (d[0])
                    func_writelog('a', logloc, txt + '\n')
                    print(txt)
                else:
                    txt = "%s -> %s" % (d[0], d[1])
                    func_writelog('a', logloc, txt + '\n')

                    print(txt)
                    subdlist[i] = txt
                    if d[1] in subiplist.keys():
                        subiplist[d[1]].append(d[0])
                    else:
                        subiplist[d[1]] = [d[0]]
                    i += 1
        except queue.Empty:
            pass
        # make sure everyone is complete
        if threads_remaining <= 0:
            print(" ")
            print("Done. ")
            txt = 'Subdomains found : %s' % (len(subdlist))

            # Alfab. ordered result list
            func_writelog('a', logloc, '\n' + txt + '\nOrdered list:\n-------------\n')
            print(txt)
            print(' ')
            print('Ordered List:')
            for result in sorted(subdlist.values()):
                txt = result
                func_writelog('a', logloc, str(txt) + '\n')
                print(txt)
            print(' ')

            # IP-ordered result list
            txt = "IP-ordered List:"
            func_writelog('a', logloc, '\n' + txt + '\n----------------\n')
            print(txt)
            for ips in subiplist:
                txt = ips
                func_writelog('a', logloc, str(txt) + '\n')
                print(txt)
                for ipssub in subiplist[ips]:
                    txt = "      |=> %s" % (ipssub)
                    func_writelog('a', logloc, str(txt) + '\n')
                    print(txt)

            end = datetime.now()
            time_stamp_end = int(time.time())
            duration = int(time_stamp_end) - int(time_stamp_start)
            time_end = str(end.year) + "-" + str(end.month) + "-" + str(end.day) + "    " + str(end.hour) + ":" + str(
                end.minute) + ":" + str(end.second)
            txt = "Scan Ended : %s" % (time_end)
            txtB = "Duration : %ss" % (duration)
            func_writelog('a', logloc, '\n' + txt + '\n')
            func_writelog('a', logloc, txtB + '\n')
            print(" ")
            print(txt)
            print(txtB)

            break
    return subdlist


"""
ON FIRST RUN : SETTING UP BASIC FILES AND FOLDERS
BEGIN:
"""

# -- Creating default log directory
"""
:END
ON FIRST RUN : SETTING UP BASIC FILES AND FOLDERS
"""


def checkdetails_json(jsonloc=""):
    count = 0
    time_stamp_start = int(time.time())
    now = datetime.now()
    time_start = str(now.year) + "-" + str(now.month) + "-" + str(now.day) + "    " + str(now.hour) + ":" + str(
        now.minute) + ":" + str(now.second)


    def write_json(data, filename='details.json'):
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)

    with open('details.json') as json_file:
        data = json.load(json_file)


        temp = data['Detail of sessoin']

        details_of_session = {"Time_start": time_start,
                              "count":(int(temp[-1]["count"])+1),
                              "json_loc":jsonloc
                              }
        # appending data to emp_details
        temp.append(details_of_session)

    write_json(data)
    return details_of_session["count"]


def main(domain_name=None, sub_domain_list=None, logfile_location=None):

    logdir = "log"
    if not os.path.exists(logdir):
        os.makedirs(logdir)
        txt = "Directory 'log/' created"
        print(txt)
    target = domain_name
    # Target
    print("\n")
    if (domain_name is None):
        target = input("Target domain name (eg. google.com) : ")

    # Subs

    sub_files: Tuple[str, str, str, str, str, str, str] = (
        "", "subs/subs_xs.txt", "subs/subs_s.txt", "subs/subs_m.txt", "subs/subs_l.txt", "subs/subs_xl.txt",
        "subs/subs_testing")

    choosen_sub = sub_domain_list

    if sub_domain_list is None:
        print("Select a subdomain list :\n1. Xtra Small\n2. Small\n3. Medium\n4. Large\n5. Xtra Large")
        choosen_sub = input("List : ")

    hosts = open(sub_files[int(choosen_sub)]).read().split("\n")

    threads = []
    # Action
    resolve_list = check_resolvers("cnf/resolvers.txt", threads)
    # signal.signal(signal.SIGINT, killme)

    target = target.strip()
    if target:

        """ Every run : create log file """
        # -- Creating log file in directory 'log' --#

        now = datetime.now()
        time_start = str(now.year) + "-" + str(now.month) + "-" + str(now.day) + "    " + str(now.hour) + ":" + str(
            now.minute) + ":" + str(now.second)
        time_stamp_start = int(time.time())
        logfile = target.replace('.', '_') + '_' + str(now.year) + str(now.month) + str(now.day) + str(now.hour) + str(
            now.minute) + str(now.second) + ".log"
        print("Creating log : log/%s" % (logfile), )

        if logfile_location is None:
            logfile_location = logdir + "/" + logfile

        with open(logfile_location, "w") as mylog:
            os.chmod(logfile_location, 0o660)
            mylog.write("Log created by Sub-domain Scanner - " + version + " build " + build + "\n\n")
            print(".... Done")
            print(" ")
        """ """
        txt: str = "Scan Started : %s" % (time_start)
        func_writelog('a', logfile_location, txt + '\n\n')
        print(txt)
        print(" ")

        # -- Visible IP --#
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        txt = "Subdomains in %s : " % (target)
        func_writelog('a', logfile_location, txt + '\n')
        print(txt)
        result = run_target(target, hosts, resolve_list, 10, True, threads, time_stamp_start, logfile_location)
        logjsonloc=logdir + "/" + logfile[:-4] + ".json"
        with open(logjsonloc, 'w') as json_save:

            json.dump(result, json_save)
            checkdetails_json(logjsonloc)

        return result


if __name__ == '__main__':
    main()
