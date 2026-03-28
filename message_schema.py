#!/usr/bin/python
# -*- coding: utf-8 -*-
# message_schema.py

from __future__ import print_function

import time
import uuid

class Message(object):
    """
    Inter-process message container.

    Fields kept simple for Py2.7 + multiprocessing pickling.
    """
    def __init__(self,
                 source,
                 msg_type,
                 payload=None,
                 target=None,
                 request_id=None,
                 msg_id=None,
                 timestamp=None):
        self.source = source
        self.type = msg_type
        self.payload = payload if payload is not None else {}

        # routing / correlation
        self.target = target            # e.g. "engine" or "sensor"
        self.request_id = request_id    # correlation id for RPC pairs
        self.msg_id = msg_id or self._new_id()

        self.timestamp = timestamp if timestamp is not None else time.time()

    def _new_id(self):
        # uuid4 exists in py2.7
        return str(uuid.uuid4())

    def __repr__(self):
        return "Message(type=%r source=%r target=%r request_id=%r payload=%r)" % (
            self.type, self.source, self.target, self.request_id, self.payload
        )