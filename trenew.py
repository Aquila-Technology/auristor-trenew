#!/usr/bin/env python3

# Simple script that will funciton in place of krenew for maintaining Auristor or OpenAFS tokens
#
# required system packages and pip modules
#
# MacOS: 
#        sudo -E pip3 install python-daemon
#
# RHEL7:
#        yum -y install python-daemon
#        pip3 install python-daemon
#
# Ubuntu 16.04: 
#        apt install python3-pip
#        pip3 install python-daemon
#
# License: MIT

import sys
import os
import time
import argparse
import logging
import subprocess
from datetime import timedelta
try:
  from systemd.journal import JournalHandler
except:
  from logging.handlers import SysLogHandler
import daemon
from daemon import pidfile

debug_p = False

def run(*popenargs, **kwargs):
    input = kwargs.pop("input", None)
    check = kwargs.pop("handle", False)

    if input is not None:
        if 'stdin' in kwargs:
            raise ValueError('stdin and input arguments may not both be used.')
        kwargs['stdin'] = subprocess.PIPE

    process = subprocess.Popen(*popenargs, **kwargs)
    try:
        stdout, stderr = process.communicate(input)
    except:
        process.kill()
        process.wait()
        raise
    retcode = process.poll()
    if check and retcode:
        raise subprocess.CalledProcessError(
            retcode, process.args, output=stdout, stderr=stderr)
    return retcode, stdout, stderr

def convert_to_timedelta(time_val):
    """
    Given a *time_val* (string) such as '5d', returns a timedelta object
    representing the given value (e.g. timedelta(days=5)).  Accepts the
    following '<num><char>' formats:
    
    =========   ======= ===================
    Character   Meaning Example
    =========   ======= ===================
    s           Seconds '60s' -> 60 Seconds
    m           Minutes '5m'  -> 5 Minutes
    h           Hours   '24h' -> 24 Hours
    d           Days    '7d'  -> 7 Days
    =========   ======= ===================
    
    Examples::
    
        >>> convert_to_timedelta('7d')
        datetime.timedelta(7)
        >>> convert_to_timedelta('24h')
        datetime.timedelta(1)
        >>> convert_to_timedelta('60m')
        datetime.timedelta(0, 3600)
        >>> convert_to_timedelta('120s')
        datetime.timedelta(0, 120)
    """
    num = int(time_val[:-1])
    if time_val[-1].isdigit():
        return timedelta(minutes=num)
    elif time_val.endswith('s'):
        return timedelta(seconds=num)
    elif time_val.endswith('m'):
        return timedelta(minutes=num)
    elif time_val.endswith('h'):
        return timedelta(hours=num)
    elif time_val.endswith('d'):
        return timedelta(days=num)

def setSleep(keep_alive):
    return convert_to_timedelta(keep_alive).total_seconds()

def trenew(args):
    ### This does the "work" of the daemon

    # setup logging
    logger = logging.getLogger('trenew')
    try:
        logger.addHandler(JournalHandler())
    except:
        logger.addHandler(SysLogHandler())
    if not args.background:
        logger.addHandler(logging.StreamHandler(sys.stdout))
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    logger.debug("trenew thread started with args: %s" % args)

#    if args.log_file == True:
#        fh = logging.FileHandler(args.log_file)
#        fh.setLevel(logging.DEBUG)
#        formatstr = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
#        formatter = logging.Formatter(formatstr)
#        fh.setFormatter(formatter)
#        logger.addHandler(fh)

    while True:
        logger.debug("entering loop")
        #logger.info("this is an INFO message")
        #logger.error("this is an ERROR message")

        logger.info("running %s" % args.aklog_path)
        try:
            aklog_call = subprocess.run([args.aklog_path, '-d', args.aklog_options], text=True, check=args.exit_immediately)
        except:
            aklog_call = subprocess.run([args.aklog_path, '-d', args.aklog_options], check=args.exit_immediately)
        logger.debug(aklog_call.stdout)
        logger.debug(aklog_call.stderr)
        logger.debug(aklog_call)

        if aklog_call.returncode != 0:
            logger.warning("aklog returned %d" % aklog_call.returncode)
            sleepTime = setSleep(args.obsess)
            logger.debug("we think we do not have a good token, obsessiong %d", sleepTime)
        else:
            sleepTime = setSleep(args.keep_alive)
            logger.debug("we think we do have a good token, sleeping for %d", sleepTime)

        time.sleep(sleepTime)


def start_daemon(args):
    ### This launches the daemon in its context

    #print(args);
    #print(args.background);

    if not args.background:
        stdout = sys.stdout
        stderr = sys.stderr
    else:
        stdout = None
        stderr = None

    ### XXX pidfile is a context
    with daemon.DaemonContext(
        stdout=stdout,
        stderr=stderr,
        working_directory=str(os.path.expanduser('~')),
        umask=0o002,
        pidfile=pidfile.TimeoutPIDLockFile(args.pid_file),
        detach_process=args.background
        ) as context:
        trenew(args)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Example daemon in Python")
    parser.add_argument('-c', '--pid-file', help="path to pid file", default='/var/run/user/'+str(os.getuid())+'/trenew.pid')
#    parser.add_argument('-l', '--log-file', default=False)
    parser.add_argument('-b', '--background', help='Fork and run in the background', action='store_true')
    #parser.add_argument('-i', '--ignore-errors', help='Kepp running even if aklog returns an error', action='store_true')
    parser.add_argument('-x', '--exit-immediately', help='Exit immediately on an error', action='store_true')
    parser.add_argument('-K', '--keep-alive', help='Check token every defined internal.  default is minutes, but takes s, m, h d.  eg 30s.', default='5m')
    parser.add_argument('-H', '--how-many', help='Check for happy token, one that does not expire in less than <limit> time units, and exit 0 if ok, otherwise renew token. default is minutes, but takes s, m, h, d. eg 30s', default='1h')
    parser.add_argument('-t', '--token', help='Since the whole point of this program is to get a token and cannot be disabled.  this flag does nothing.', default='/usr/bin/aklog')
    parser.add_argument('--aklog-path', help='path to aklog', default='/usr/bin/aklog')
    parser.add_argument('-o', '--aklog-options', help='options to pass to aklog', default="")
    parser.add_argument('-O', '--obsess', help='if fails, obsess about getting tokens by retrying in time interval. setting to 0 will disable.  eg 1m', default='1m')
    parser.add_argument('-v', '--verbose', help='crank up verbosity, logging to journalctl or syslog. if not backgrounded, also print to stdout', action='store_true')

    args = parser.parse_args()

    start_daemon(args)
