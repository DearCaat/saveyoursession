#!/usr/bin/env python3
"""Scheduler entry point: run this daily from cron/Task Scheduler/launchd."""
import sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
import server
print(server.sync())
