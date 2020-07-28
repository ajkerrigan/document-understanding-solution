import boto3
from botocore.exceptions import ClientError
import json
import os
from helper import S3Helper


class KendraHelper:


    #
    #   This function instruct Kendra to index a pdf document in s3
    #
    #   region:                 region of Kendra index
    #   kendraIndexId:          Kendra index id
    #   kendraRoleArn:          a role that Kendra can assume to read the s3 bucket
    #   s3bucket:               bucket name where document to index exists
    #   s3key:                  key of the document to index
    #   documentId:             the document id generated by DUS
    #   tag                     the ACL membership of the document access.
    #
    def indexDocument(self,
                      kendraIndexId,
                      kendraRoleArn,
                      s3bucket,
                      s3key,
                      documentId,
                      documentExtension,
                      tag = 'everybody'):

        #import pdb
        #pdb.set_trace()
  
        print("KendraHelper.indexDocument: s3key: " + s3key)
        print("KendraHelper.indexDocument: documentId: " + documentId)
        print("KendraHelper.indexDocument: documentExtension: " + documentExtension)
        
        # try to fetch the optional kendra policy file that may have been uploaded to s3
        # along with the document
        originalDocumentName = s3key[:-15].split('/')[3]
        policyFilepath = "public/" + documentId + "/" + originalDocumentName + "." + documentExtension + ".metadata.json"
        s3helper = S3Helper()
        policyData = None
        
        try:
            policyData = s3helper.readFromS3(s3bucket,
                                             policyFilepath,
                                             os.environ['AWS_REGION'])
    
        # the normal case of a file not provided is handled.  If any other error
        # occur the indexing will proceed without the membership tags in the policy file
        except ClientError as e:
            policyData = None
            # NoSuchKey is the expected exception, any other means an error
            if e.response['Error']['Code'] != 'NoSuchKey':
                print("ClientError exception from s3helper.readFromS3: " + str(e))
            else:
                print("no kendra policy file found, only default membership will be applied")
                    
        # an error that should be investigated
        except Exception as e:
            policyData = None
            print("unspecified exception from s3helper.readFromS3: " + str(e))
        
        # accessControlList will contain the default persona membership, the function call provided
        # tags if different from default, and any additonal membership tags in the metadata policy
        # json file was given in s3 with the document
        accessControlList = []
        
        # the default membership for all documents
        defaultMembership = {}
        defaultMembership['Name'] = 'everybody'
        defaultMembership['Type'] = 'GROUP'
        defaultMembership['Access'] = 'ALLOW'
        accessControlList.append(defaultMembership)
        
        # if a different membership tag was provided in the function call, add it
        # as well
        if tag != 'everybody':
            tagMembership['Name'] = tag
            tagMembership['Type'] = 'GROUP'
            tagMembership['Access'] = 'ALLOW'
            accessControlList.append(tagMembership)
        
        # if the policy file exists, it may contain additional membership tags.  Parsing
        # error may happen and will be caught
        try:
            if policyData != None:
                
                policyAccessList = json.loads(policyData)
                
                for membership in policyAccessList['AccessControlList']:
                    
                    # no need for tags in the policy that may have been already added above
                    if membership['Name'] != 'everybody' and membership['Name'] != tag:
                        accessControlList.append(membership)
        
        # indexing will proceed without the membership tags in the policy file
        except Exception as e:
            print("exception while processing policy file " + policyFilepath + str(e))
    
        print("document will have the following membership policy in Kendra: " + json.dumps(accessControlList))
    
        # get Kendra to index the document along with memberships
        kendraclient = client = boto3.client('kendra', region_name=os.environ['AWS_REGION'])
        response = client.batch_put_document(IndexId=kendraIndexId,
                                             RoleArn=kendraRoleArn,
                                             Documents=[
                                                {
                                                'Id': documentId,
                                                'S3Path': {
                                                    'Bucket': s3bucket,
                                                    'Key': s3key
                                                        },
                                                'AccessControlList': accessControlList,
                                                'ContentType': 'PDF'}])

        return

    #
    #   This function instruct Kendra to remove a pdf document from its index
    #
    #   region:                 region of Kendra index
    #   kendraIndexId:          Kendra index id
    #   documentId:             the document id generated by DUS
    #
    def deindexDocument(self,
                        kendraIndexId,
                        documentId):

        kendraclient = client = boto3.client('kendra', region_name=os.environ['AWS_REGION'])

        response = client.batch_delete_document(IndexId=kendraIndexId,
                                                DocumentIdList=[documentId])

        return

    #
    #   This function seaches Kendra using a natural language query string and a
    #   user membership tag (healthprovider, scientist, generalpublic)
    #
    #   region:                 region of Kendra index
    #   kendraIndexId:          Kendra index id
    #   requestBody:            POST body of json search, see example below.
    #
    #   { "query":"my keywords",
    #     "tag":"scientist",
    #     "pageNumber":1,       pagination is done by providing the page number needed in each request
    #     "pageSize":100        each page may have a maximum of 100 results
    #   }
    #
    def search(self,
               kendraIndexId,
               requestBody):

        search = json.loads(requestBody)

        client = client = boto3.client('kendra', region_name=os.environ['AWS_REGION'])

        if 'tag' in search and search['tag'] != None:
            response = client.query(
                QueryText=search['query'],
                IndexId=kendraIndexId,
                AttributeFilter={
                    "OrAllFilters": [
                        {
                            "EqualsTo": {
                            "Key": "_group_ids",
                            "Value": {
                                "StringListValue": [search['tag']]
                                }
                            }
                        }
                    ]
                },
                PageNumber=search['pageNumber'],
                PageSize=search['pageSize']
            )

        else:
            response = client.query(
                QueryText=search['query'],
                IndexId=kendraIndexId,
                PageNumber=search['pageNumber'],
                PageSize=search['pageSize']
            )

        return response

    #
    #   This function tells Kendra that a specific search result from a previous
    #   results set is relevant or not. Kendra will use this hint in subsequent
    #   searches.
    #
    #   region:                 region of Kendra index
    #   kendraIndexId:          Kendra index id
    #   requestBody:            POST json body of feedback,  see example below
    #
    #   {  "queryId":"4c97e09a-5a97-4d3a-beb6-9362fb90fa16",
    #      "resultId":"4c97e09a-5a97-4d3a-beb6-9362fb90fa16-df5306d5-085d-4c51-8eaf-4add4848643b",
    #      "relevance":true
    #   }
    #
    def submitFeedback(self,
                       kendraIndexId,
                       requestBody):

        feedback = json.loads(requestBody)

        client = client = boto3.client('kendra', region_name=os.environ['AWS_REGION'])

        relevance = 'RELEVANT'

        if feedback['relevance'] == False:
            relevance = 'NOT_RELEVANT'

        response = client.submit_feedback(IndexId=kendraIndexId,
                                          QueryId=feedback['queryId'],
                                          RelevanceFeedbackItems=[
                                              {
                                                  'ResultId': feedback['resultId'],
                                                  'RelevanceValue': relevance
                                              }
                                          ])

        return
