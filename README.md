# aws-lakeformation-cloudformation-tests
This repository illustrates a "bug" that seems to appear when using CloudFormation along with Lake Formation to handle data permissions.

Given a CloudFormation stack that contains `AWS::LakeFormation::Permissions` resources which grant a certain principal access to certain columns on a Glue table, the `REVOKE` operations aren't done correctly when updating that stack to remove those certain column grants.    

## Install & run
Run in a CloudShell sandbox account (root user):
1) `git clone https://github.com/sviscaino/aws-lakeformation-cloudformation-tests.git && cd aws-lakeformation-cloudformation-tests`
2) `pip install -r requirements.txt`
3) `./main.py`

## Description

We first spin up the environment and create:
- an S3 bucket to store the CloudFormation templates
- an S3 bucket that will act as our "datalake" bucket,
- a Glue database and table with the following mock schema:

| column name | type   |
|-------------|--------|
| id          | string |
| firstName   | string |
| lastName    | string |
| age         | int    |

- an admin IAM user that is setup to be the data lake administrator in Lake Formation
- Lake Formation settings to disable the default IAM permissions on the Glue table

We then loop on each test scenario:
- we create an IAM user and access keys for the test,
- we grant the permissions by creating the CloudFormation stack that grants access to the columns specified in the test ([lakeformation-permissions.py](cfn/lakeformation-permissions.yml)),
- we then potentially update the CloudFormation stack with new parameters,
- we run an Athena `SELECT * FROM db.table` query with the credentials of the user
- we compare the output schema of this query with what is expected.

## Test scenarios

Test scenarios are located in `tests.py`.

| Test | Initially allowed                    | Allowed after update                            | Expected columns after SELECT *               | Actual columns after SELECT * | Result |
|------|--------------------------------------|-------------------------------------------------|-----------------------------------------------|-------------------------------|--------|
| 1    | included=id,lastName / excluded=     | (no update)                                   | id,lastName                                   | id,lastName                   | PASS   |
| 2    | included= / excluded=age             | (no update)                                   | id,firstName,lastName                         | id,firstName,lastName         | PASS   |
| 3    | included=id,firstName / excluded=age | (no update)                                   | id,firstName,lastName (excluded has priority) | id,firstName,lastName         | PASS   |
| 4    | included=id,lastName / excluded=     | included=id,firstName,lastName / excluded=    | id,firstName,lastName                         | id,firstName,lastName         | PASS   |
| 5    | included=id,lastName / excluded=     | included=id,lastName / excluded=age           | id,firstName,lastName (excluded has priority) |                               | FAIL   |
| 6    | included= / excluded=age             | included= / excluded=id,age                   | firstName,lastName                            |                               | FAIL   |
| 7    | included= / excluded=age             | included=firstName / excluded=age             | id,firstName,lastName (excluded has priority) |                               | FAIL   |
| 8    | included= / excluded=age             | included=firstName / excluded=id,age          | firstName,lastName (excluded has priority)    |                               | FAIL   |
| 9    | included=id,lastName / excluded=age  | included=firstName,lastName / excluded=id,age | firstName,lastName (excluded has priority)    |                               | FAIL   |
| 10   | included=id,lastName / excluded=age  | included=id,firstName,lastName / excluded=age | id,firstName,lastName                         |                               | FAIL   |
| 11   | included=id,firstName / excluded=    | included=id,lastName / excluded=              | id,lastName                                   | id,firstName,lastName         | FAIL   |

## Cleanup

To cleanup resources, run: `./cleanup.py`
