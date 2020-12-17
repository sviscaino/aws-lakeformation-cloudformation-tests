#!/usr/bin/env python3
import os
import boto3
from utils import *
from tests import *

if not bucket_exists(artifacts_bucket):
    create_artifacts_bucket()
    upload_directory_s3('cfn/', artifacts_bucket)
    deploy_stack('datalake1', 'datalake1-stack')
    change_datalake_default_security_settings() # CreateTableDefaultPermissions not supported in cfn
    deploy_stack('datalake2', 'datalake2-stack')

for i, test in enumerate(tests):
    user_name = 'test%d-user' % i
    delete_stack('test%d-lf-stack' % i)
    delete_stack('test%d-stack' % i)
    deploy_stack('iam-user', 'test%d-stack' % i, userName=user_name)
    deploy_stack(
        'lakeformation-permissions',
        'test%d-lf-stack' % i,
        userName=user_name,
        shownColumns=test['initial']['shownColumns'],
        hiddenColumns=test['initial']['hiddenColumns'])
    if 'updateWith' in test:
        update_stack(
            'lakeformation-permissions',
            'test%d-lf-stack' % i,
            userName=user_name,
            shownColumns=test['updateWith']['shownColumns'],
            hiddenColumns=test['updateWith']['hiddenColumns'])
    access_key_id, secret_access_key = recreate_access_keys(user_name)
    athena = boto3.client('athena', aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key)
    run_test(i, athena)