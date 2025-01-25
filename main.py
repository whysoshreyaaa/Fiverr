from elasticsearch import Elasticsearch
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ElasticsearchClient_SSLConnection:
    def __init__(self):
        url = "elasticsearch-190712-0.cloudclusters.net"
        port = 10043
        try:
            self.conn = Elasticsearch(
                hosts=[{"host": url, "port": port, "scheme": "https"}],
                http_auth=("elastic", "HmtoTvKY"),
                verify_certs=True,
                ca_certs="/Users/billionaire/Downloads/ca_certificate.pem",
            )
            if not self.conn.ping():
                logger.error("Ping failed - using connection anyway")
        except Exception as e:
            logger.error(f"Elasticsearch init error: {e}")
            raise

try:
    es_client = ElasticsearchClient_SSLConnection()
except Exception as e:
    es_client = None

class SearchResponse(BaseModel):
    total: int
    results: List[dict]
    facets: dict

@app.get("/api/search", response_model=SearchResponse)
async def search(
    q: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    yearFrom: Optional[str] = None,
    yearTo: Optional[str] = None,
    court: Optional[str] = None
):
    if not es_client:
        raise HTTPException(status_code=500, detail="Elasticsearch connection failed")

    try:
        from_value = (page - 1) * size
        must_conditions = []

        # Search query
        if q:
            must_conditions.append({
                "multi_match": {
                    "query": q,
                    "fields": ["*"]
                }
            })

        # Year range filter
        if yearFrom or yearTo:
            year_range = {}
            if yearFrom:
                year_range["gte"] = str(yearFrom).zfill(4)  # Ensure 4-digit format (e.g., "1950")
            if yearTo:
                year_range["lte"] = str(yearTo).zfill(4)
            must_conditions.append({
                "range": {
                    "JudgmentMetadata.CaseDetails.JudgmentYear.keyword": year_range  # Correct nested path
                }
            })
        # Court filter using script
        if court in ["SC", "HC"]:
            must_conditions.append({
                "script": {
                    "script": {
                        "source": "doc['_id'].value.startsWith(params.prefix)",
                        "params": {"prefix": court}
                    }
                }
            })

        query = {"bool": {"must": must_conditions or [{"match_all": {}}]}}

        # Aggregations
        aggs = {
            "years": {
                "terms": {
                    "field": "JudgmentMetadata.CaseDetails.JudgmentYear.keyword",
                    "size": 50,
                    "order": {"_key": "desc"}
                }
            },
            "courts": {
                "terms": {
                    "script": {
                        "source": "doc['_id'].value.substring(0,2)",
                        "lang": "painless"
                    },
                    "size": 50  # Increased from 2 to capture all court types
                }
            }
        }

        response = es_client.conn.search(
            index="judgements-index",
            body={"query": query, "aggs": aggs, "from": from_value, "size": size}
        )

        # Process results
        results = [{"id": hit["_id"], **hit["_source"]} for hit in response["hits"]["hits"]]
        
        # Process court facets
        court_buckets = [
            {"key": "SC", "doc_count": 0},
            {"key": "HC", "doc_count": 0}
        ]
        for bucket in response["aggregations"]["courts"]["buckets"]:
            if bucket["key"] in ["SC", "HC"]:
                for cb in court_buckets:
                    if cb["key"] == bucket["key"]:
                        cb["doc_count"] = bucket["doc_count"]

        return {
            "total": response["hits"]["total"]["value"],
            "results": results,
            "facets": {
                "years": response["aggregations"]["years"],
                "courts": {"buckets": court_buckets}
            }
        }
        
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/autocomplete")
async def autocomplete(q: str = Query(...)):
    try:
        response = es_client.conn.search(
            index="judgements-index",
            body={
                "suggest": {
                    "judgement-suggest": {
                        "prefix": q,
                        "completion": {
                            "field": "suggest",
                            "skip_duplicates": True,
                            "size": 5
                        }
                    }
                }
            }
        )
        return [opt["text"] for opt in response["suggest"]["judgement-suggest"][0]["options"]]
    except Exception as e:
        return []