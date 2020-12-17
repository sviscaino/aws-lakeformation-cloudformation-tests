import os
import boto3
import time
import pretty_errors
import re
from yaspin import yaspin
from tests import *
from colored import fg, attr

account_id = boto3.client('sts').get_caller_identity().get('Account')
region = boto3.session.Session().region_name
artifacts_bucket = 'artifacts-%s' % account_id
datalake_bucket = 'datalake-%s' % account_id

s3 = boto3.client('s3')
cfn = boto3.client('cloudformation')
lfn = boto3.client('lakeformation')
iam = boto3.client('iam')

def deploy_stack(template, stack, **kwargs):
    with yaspin(text='Deploying stack %s from template %s' % (stack, template)) as spinner:
        cfn.create_stack(
            StackName = stack,
            TemplateURL = 'https://s3.amazonaws.com/%s/%s.yml' % (artifacts_bucket, template),
            Parameters = [{'ParameterKey': k, 'ParameterValue': v} for k, v in kwargs.items()],
            Capabilities = ['CAPABILITY_NAMED_IAM']
        )
        while True:
            all_stacks = cfn.describe_stacks(StackName = stack)
            current_stack = next(s for s in all_stacks['Stacks'] if s['StackName'] == stack)
            current_state = current_stack['StackStatus']
            if current_state != 'CREATE_IN_PROGRESS':
                spinner.ok("✔️")
                break
            time.sleep(5)
        if current_state != 'CREATE_COMPLETE':
            spinner.fail("⨯")
            raise Exception('stack status was %s' % current_state)

def update_stack(template, stack, **kwargs):
    with yaspin(text='Updating stack %s' % stack) as spinner:
        cfn.update_stack(
            StackName = stack,
            TemplateURL = 'https://s3.amazonaws.com/%s/%s.yml' % (artifacts_bucket, template),
            Parameters = [{'ParameterKey': k, 'ParameterValue': v} for k, v in kwargs.items()],
            Capabilities = ['CAPABILITY_NAMED_IAM']
        )
        while True:
            all_stacks = cfn.describe_stacks(StackName = stack)
            current_stack = next(s for s in all_stacks['Stacks'] if s['StackName'] == stack)
            current_state = current_stack['StackStatus']
            if current_state != 'UPDATE_IN_PROGRESS':
                spinner.ok("✔️")
                break
            time.sleep(5)
        if current_state != 'UPDATE_COMPLETE' and current_state != 'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS':
            spinner.fail("⨯")
            raise Exception('stack status was %s' % current_state)

def delete_stack(stack, **kwargs):
    if stack_exists(stack):
        with yaspin(text='Deleting stack %s' % stack) as spinner:
            cfn.delete_stack(StackName=stack, **kwargs)
            current_state = True
            while True:
                all_stacks = []
                try:
                    all_stacks = cfn.describe_stacks(StackName = stack)
                except:
                    spinner.ok("✔️")
                    return
                current_stack = next(s for s in all_stacks['Stacks'] if s['StackName'] == stack)
                current_state = current_stack['StackStatus']
                current_reason = current_stack.get('StackStatusReason')
                if current_state != 'DELETE_IN_PROGRESS':
                    spinner.ok("✔️")
                    break
                time.sleep(5)
            if current_state == 'DELETE_FAILED' and stack.startswith('datalake2') and 'RetainResources' not in kwargs:
                spinner.fail("⨯")
                delete_stack(stack, RetainResources=['LakeFormationDataLocation'])
            elif current_state == 'DELETE_FAILED' and stack.endswith('-lf-stack') and 'RetainResources' not in kwargs:
                failed_to_delete = re.search('failed to delete: \[([^\]]+)\]', current_reason).group(1)
                spinner.text = 'failed to delete %s' % failed_to_delete
                spinner.fail("⨯")
                revoke_all_lakeformation_permissions(stack.replace('-lf-stack', '-user'))
                delete_stack(stack, RetainResources=[s.strip() for s in failed_to_delete.split(',')])
            elif current_state != 'DELETE_COMPLETE':
                spinner.fail("⨯")
                raise Exception('stack status was %s' % current_state)

def upload_directory_s3(path, bucket):
    with yaspin(text='uploading %s to s3 bucket %s' % (path, bucket)) as spinner:
        for root, dirs, files in os.walk(path):
            for file in files:
                s3.upload_file(os.path.join(root, file), bucket, file)
        spinner.ok("✔️")

def recreate_access_keys(user_name):
    with yaspin(text='recreating access keys for %s' % user_name) as spinner:
        existing = [a['AccessKeyId'] for a in iam.list_access_keys(UserName = user_name)['AccessKeyMetadata']]
        for access_key_id in existing:
            iam.delete_access_key(UserName = user_name, AccessKeyId = access_key_id)
        access_key_info = iam.create_access_key(UserName=user_name)['AccessKey']
        spinner.text = 'recreating access keys for %s [%s - wait 30 sec]' % (user_name, access_key_info['AccessKeyId'])
        time.sleep(30)
        spinner.ok("✔️")
        return access_key_info['AccessKeyId'], access_key_info['SecretAccessKey']

def empty_bucket(bucket_name):
    if bucket_exists(bucket_name):
        with yaspin(text='Emptying bucket %s' % bucket_name) as spinner:
            boto3.resource('s3').Bucket(bucket_name).objects.all().delete()
            spinner.ok("✔️")

def delete_bucket(bucket_name):
    if bucket_exists(bucket_name):
        with yaspin(text='Deleting bucket %s' % bucket_name) as spinner:
            s3.delete_bucket(Bucket=bucket_name)
            spinner.ok("✔️")

def bucket_exists(bucket):
    try:
        s3.head_bucket(Bucket=bucket)
        return True
    except:
        return False

def stack_exists(stack):
    try:
        return len(cfn.describe_stacks(StackName = stack)['Stacks']) >= 1
    except:
        return False

def create_artifacts_bucket():
    with yaspin(text='creating artifacts bucket') as spinner:
        s3.create_bucket(Bucket=artifacts_bucket, CreateBucketConfiguration={'LocationConstraint': region})
        spinner.ok("✔️")
def change_datalake_default_security_settings():
    lfn.put_data_lake_settings(
        DataLakeSettings={
            'DataLakeAdmins': [{
                'DataLakePrincipalIdentifier': 'arn:aws:iam::%s:user/admin-user' % account_id
            }],
            'CreateDatabaseDefaultPermissions': [],
            'CreateTableDefaultPermissions': []
        })

def run_athena_query(athena, query):
    query_id = athena.start_query_execution(
        QueryString=query,
        ResultConfiguration={
            'OutputLocation': ('s3://athena-output-%s/' % account_id)
        })['QueryExecutionId']
    while True:
        query_info = athena.get_query_execution(QueryExecutionId=query_id)
        query_status = query_info['QueryExecution']['Status']['State']
        if query_status != 'QUEUED' and query_status != 'RUNNING':
            break
        time.sleep(2)
    if query_status != 'SUCCEEDED':
        raise Exception('query status was %s' % query_status)
    return athena.get_query_results(QueryExecutionId = query_id)

def run_test(i, athena):
    prefix = '[test %d/%d]' % (i+1, len(tests))
    with yaspin(text=prefix) as spinner:
        query = 'SELECT * FROM datalake_db.account_table'
        spinner.text = '%s running athena query' % prefix
        results = run_athena_query(athena, query)
        columns = frozenset([ col['Name'].lower() for col in results['ResultSet']['ResultSetMetadata']['ColumnInfo'] ])
        expected = frozenset([ col.lower() for col in tests[i]['expected'] ])
        if columns == expected:
            spinner.text = '%s %sPASS%s' % (prefix, fg('green'), attr('reset'))
            spinner.ok("✔️")
        else:
            spinner.text = '%s %sFAIL%s - expected %s, got %s' % (prefix, fg('red'), attr('reset'), ",".join(expected), ",".join(columns))
            spinner.fail("⨯")

def revoke_all_lakeformation_permissions(user_name):
    with yaspin(text='revoking all Lake Formation permissions as stack delete failed') as spinner:
        table_permissions = lfn.list_permissions(
            Principal = {'DataLakePrincipalIdentifier': 'arn:aws:iam::%s:user/%s' % (account_id, user_name)},
            Resource = {
                'Table':{
                    'DatabaseName': 'datalake_db',
                    'Name': 'account_table'
                }
            }
        )['PrincipalResourcePermissions']
        for permission in table_permissions:
            lfn.revoke_permissions(**permission)

        db_permissions = lfn.list_permissions(
            Principal={'DataLakePrincipalIdentifier': 'arn:aws:iam::%s:user/%s' % (account_id, user_name)},
            Resource={'Database': {'Name': 'datalake_db'}}
        )['PrincipalResourcePermissions']
        for permission in db_permissions:
            lfn.revoke_permissions(**permission)
        spinner.ok("✔️")
