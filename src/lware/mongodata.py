import os
from uuid import UUID
import logging, traceback
from pymongo import MongoClient
from pymongo.collection import Collection
from bson.json_util import dumps, loads
from bson.objectid import ObjectId
import json
from .utils import failsafe



#Utils

@failsafe
def validate_data(schema, data):  

    if isinstance(data, dict):
        data = schema().load(data)

    if isinstance(data, list):
        data = schema(many=True).load(data)

    return data



def valid_uuid4(uuid_string):
    try:
        UUID(uuid_string, version=4)
        return True
    except ValueError:
        return False


def valid_object_id(oid_string):
    try:
        ObjectId(oid_string)
        return True
    except:
        return False


def parse_oid(oid):
    if isinstance(oid, ObjectId):
        return json.loads(dumps(oid))['$oid']
    return oid


def parse_doc(doc):
    if not isinstance(doc, dict): return doc
    if not "_id" in doc: return doc

    return dict(doc, **{"_id": parse_oid(doc["_id"])})
    

def parse_match(match):
    oid, uid, key = None, None, None
    if isinstance(match, str): 
        if valid_uuid4(match): 
            match = {"_id": match}
            oid, uid = False, True
        elif valid_object_id(match):
            match = {"_id": ObjectId(match)}
            oid, uid = True, False
        else:
            key = match
    return oid, uid, key, match


class MongoData:
    """
        Wrapper on pymongo with added data validation based on marshmallow
        
    """

    @staticmethod
    @failsafe
    def get_collection(collection, db_name, conn_string):
        
        conn_string = conn_string or os.getenv("MONGO_CONNECTION_STRING")
        db_name     = db_name     or os.getenv("MONGO_DB_NAME") or os.getenv("MONGO_DATABASE_NAME")
        collection  = collection  or os.getenv("MONGO_COLLECTION_NAME") or "data"

        # print(db_name, collection)

        if not conn_string and db_name and collection:
            raise Exception(
                "Didn't found: MONGO_COLLECTION_NAME, MONGO_DATABASE_NAME, MONGO_CONNECTION_STRING"
            )

        connection = MongoClient(conn_string)
        collection = connection[db_name][collection]
        
        return collection


    @staticmethod
    @failsafe
    def insert(schema, data, collection=None, db_name=None, conn_string=None):
        """
            Insert validated documents in database.

            :collection - collection name
            :data       - data in dict or list of dicts format
            :schema     - Marshmallow schema class 
            :db_name    - specify other db if needed, by default is MONGO_DATABASE_NAME from .env
            :conn_string - mongodb connection string

            returns a list of ids inserted in the database in the order they were added
        """
  
        collection = MongoData.get_collection(collection, db_name, conn_string)
        if not isinstance(collection, Collection): 
            return collection 

        data = validate_data(schema, data)
        if isinstance(data, str): return data

        if isinstance(data, dict):
            inserted_id = parse_oid(collection.insert_one(data).inserted_id)
            return [inserted_id]
    
        if isinstance(data, list):
            inserted_ids = collection.insert_many(data).inserted_ids
            return [parse_oid(oid) for oid in inserted_ids]

        raise Exception(f"Can't interpret validated data: {data}")



    @staticmethod
    @failsafe
    def fetch(match, collection=None, as_list=False, db_name=None, conn_string=None):
        """
            Get data from mongo, based on match dict or string id.
            
            :collection - collection name
            :match      - id as string or dict filter query
            :as_list    - return data found as list by default returns a generator
            :db_name    - specify other db if needed by default is MONGO_DATABASE_NAME from .env

            returns a generator of documents found or if as_list=True a list of documents found  

        """
        
        oid, uid, key, match = parse_match(match)

        collection = MongoData.get_collection(collection, db_name, conn_string)
        if not isinstance(collection, Collection): return collection 

        if oid or uid:
            found_docs = collection.find(match)
            doc = list(found_docs)[0]
            if oid: doc = parse_doc(doc)
            return doc

        if key: 
            found_docs = collection.distinct(key)
        else:
            found_docs = collection.find(match)
            

        if as_list: 
            return [parse_doc(doc) for doc in found_docs]
            
        return (parse_doc(doc) for doc in found_docs)    
            

    @staticmethod
    @failsafe
    def update(schema, match, new_data, collection=None, db_name=None, conn_string=None):
        """
           Update documents based on match query.
            
            :schema      - Marshmallow schema class
            :match       - id as string or dict filter query
            :new_data    - data dict which needs to be updated
            :collection  - collection name
            :db_name     - specify other db if needed by default is MONGO_DATABASE_NAME from .env
            
            returns number of modified documents

        """

        _, _, _, match = parse_match(match)
       
        collection = MongoData.get_collection(collection, db_name, conn_string)
        if not isinstance(collection, Collection): return collection 

        new_data = validate_data(schema, new_data)
        if isinstance(new_data, str): return new_data


        updated_docs_nbr = collection.update_many(
            filter=match,
            update={"$set": new_data},
            upsert=True
        ).modified_count
        
        return updated_docs_nbr


    @staticmethod
    @failsafe
    def delete(match, collection=None, db_name=None, conn_string=None):
        """

           Delete documents based on match query.

            :collection  - collection name
            :match       - id as string or dict filter query
            :db_name     - specify other db if needed by default is MONGO_DATABASE_NAME from .env
            
            returns number of deleted documents

        """

        _, _, _, match = parse_match(match)

        collection = MongoData.get_collection(collection, db_name, conn_string)
        if not isinstance(collection, Collection): return collection 

        deleted_docs_nbr = collection.delete_many(
            filter=match,
        ).deleted_count
        
        return deleted_docs_nbr

    
    @staticmethod
    @failsafe
    def aggregate(pipeline, collection=None, as_list=False, db_name=None, conn_string=None):
        """
           Fetch documents based on pipeline queries.
           https://docs.mongodb.com/manual/reference/operator/aggregation-pipeline/
            
            :collection - collection name
            :pipeline   - list of query stages
            :as_list    - return data found as list by default returns a generator
            :db_name    - specify other db if needed by default is MONGO_DATABASE_NAME from .env
            
            returns a generator of documents found or a list if as_list=True

        """

        collection = MongoData.get_collection(collection, db_name, conn_string)
        if not isinstance(collection, Collection): return collection 

        found_docs = collection.aggregate(pipeline, allowDiskUse=True)

        if as_list: return [parse_doc(doc) for doc in found_docs]
            
        return (parse_doc(doc) for doc in found_docs)    
        
    
    
    
     