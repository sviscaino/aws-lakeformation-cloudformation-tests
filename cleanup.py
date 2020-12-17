#!/usr/bin/env python3
import os
import boto3
from utils import *
from tests import *

for i, _ in enumerate(tests):
    delete_stack('test%d-lf-stack' % i)
    delete_stack('test%d-stack' % i)

empty_bucket(artifacts_bucket)
delete_bucket(artifacts_bucket)
empty_bucket(datalake_bucket)
empty_bucket('athena-output-%s' % account_id)
delete_stack('datalake2-stack')
delete_stack('datalake1-stack')
delete_stack('iam-admin-stack')
