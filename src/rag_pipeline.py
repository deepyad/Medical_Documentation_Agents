"""
RAG pipeline with hybrid retrieval (dense + sparse).

This module implements Section 3 of the requirement doc: "RAG Pipeline Improvements".

The RAG pipeline is designed to find similar devices from a corpus of 300,000 FDA 510(k) summary
documents. It uses hybrid retrieval combining dense vector embeddings with sparse keyword-based
retrieval for improved accuracy and recall.

Key Design Principles (from Section 3):
- Hybrid Retrieval Models: Combine dense vector similarity with sparse methods (BM25)
- Semantic Chunking: Use semantic-aware chunking instead of fixed-size chunks
- Efficient Vector Indexing: Use hierarchical indexes (HNSW) for fast similarity search
- Re-ranking: Apply re-ranking for better result ordering
- Query Expansion: Multi-query rewriting and expansion

Current Setup (from Section 3):
1. Conversion of all 510k summaries to markdown documents
2. Chunk each document in fixed 300-400 long segments
3. Embed as dense vectors using OAI text-embedding-ada-002
4. Store in Qdrant
5. Agent creates query string from device information
6. Query gets embedded and cosine similarity is calculated
7. n most similar chunks are returned

Improvements Implemented:
- Hybrid retrieval (dense + sparse)
- Semantic chunking (paragraph-based)
- BM25 for keyword matching
- Combined scoring with weighted fusion

Reference: requirement doc - Section 3: RAG Pipeline Improvements
"""
from typing import List, Dict, Any, Optional
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from src.config import settings
from src.models import DocumentChunk, RetrievalResult


class HybridRetrieval:
    """
    Hybrid retrieval combining dense and sparse methods.
    
    This class implements the "Hybrid Retrieval Models" improvement from Section 3.
    It combines dense vector similarity (from OpenAI embeddings) with sparse retrieval
    (BM25) to capture both semantic and keyword relevance, improving overall retrieval quality.
    
    Why Hybrid Retrieval (from Section 3):
    - Dense vectors capture semantic similarity (related concepts, synonyms)
    - Sparse vectors capture exact keyword matches (device names, codes, classifications)
    - Combining both provides better recall and precision
    
    Implementation:
    - Dense: OpenAI text-embedding-ada-002 for semantic embeddings
    - Sparse: BM25 for keyword-based retrieval
    - Combined scoring with weighted fusion (default: 70% dense, 30% sparse)
    
    Reference: requirement doc - Section 3: "Hybrid Retrieval Models: Combine dense vector
               similarity (from text-embedding-ada-002) with sparse methods like BM25 to
               capture both semantic and keyword relevance, improving overall retrieval quality"
    """
    
    def __init__(self):
        """
        Initialize hybrid retrieval system.
        
        Sets up connections to Qdrant (vector database) and OpenAI (embeddings),
        and initializes BM25 indexes for sparse retrieval.
        
        Reference: requirement doc - Section 3: "Efficient Vector Indexing and Scaling: Use
                   hierarchical or multi-level indexes in Qdrant to optimize similarity
                   search speed and scalability"
        """
        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key
        )
        self.openai_client = OpenAI(api_key=settings.openai_api_key)
        
        # Initialize BM25 for sparse retrieval
        self.bm25_indexes: Dict[str, BM25Okapi] = {}
        self.bm25_documents: Dict[str, List[DocumentChunk]] = {}
        
        # Initialize collection if it doesn't exist
        self._ensure_collection()
    
    def _ensure_collection(self):
        """
        Ensure Qdrant collection exists.
        
        Creates the Qdrant collection if it doesn't exist. Uses HNSW (Hierarchical
        Navigable Small World) indexing for fast approximate nearest neighbor search.
        
        Reference: requirement doc - Section 3: "Qdrant uses Hierarchical Navigable Small World
                   (HNSW) for dense vectors—fast, scalable approximate nearest neighbor search"
        """
        collection_name = "device_documents"
        try:
            self.client.get_collection(collection_name)
        except Exception:
            # Create collection with 1536 dimensions for ada-002
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=1536,
                    distance=Distance.COSINE
                )
            )
    
    def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding using OpenAI.
        
        Uses OpenAI's text-embedding-ada-002 model to generate dense vector embeddings.
        These embeddings capture semantic meaning and are used for dense retrieval.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector (1536 dimensions for ada-002)
        
        Reference: requirement doc - Section 3: "Embed as dense vectors using OAI
                   text-embedding-ada-002"
        """
        response = self.openai_client.embeddings.create(
            model=settings.embedding_model,
            input=text
        )
        return response.data[0].embedding
    
    def index_chunks(
        self,
        chunks: List[DocumentChunk],
        collection_name: str = "device_documents"
    ):
        """
        Index document chunks in Qdrant.
        
        Indexes chunks in both dense (Qdrant) and sparse (BM25) indexes for hybrid retrieval.
        Stores metadata as payload for filtering and retrieval.
        
        Args:
            chunks: List of document chunks to index
            collection_name: Qdrant collection name
        
        Reference: requirement doc - Section 3: "Store both in a vector database like Qdrant
                   (or alternatives: Pinecone, Milvus). Qdrant supports HNSW vector indexing,
                   payload metadata, and hybrid retrieval"
        Reference: requirement doc - Section 3: "Optionally, store sparse indexes (e.g., TF-IDF
                   or BM25 vectors) alongside dense ones for hybrid scoring"
        """
        points = []
        
        for chunk in chunks:
            if not chunk.embedding:
                chunk.embedding = self.embed_text(chunk.content)
            
            points.append(
                PointStruct(
                    id=chunk.chunk_id,
                    vector=chunk.embedding,
                    payload={
                        "document_id": chunk.document_id,
                        "content": chunk.content,
                        "chunk_index": chunk.chunk_index,
                        **chunk.metadata
                    }
                )
            )
            
            # Update BM25 index for sparse retrieval
            if collection_name not in self.bm25_indexes:
                self.bm25_documents[collection_name] = []
            self.bm25_documents[collection_name].append(chunk)
        
        # Build BM25 index
        if collection_name in self.bm25_documents:
            tokenized_docs = [
                chunk.content.lower().split() 
                for chunk in self.bm25_documents[collection_name]
            ]
            self.bm25_indexes[collection_name] = BM25Okapi(tokenized_docs)
        
        # Upsert to Qdrant
        if points:
            self.client.upsert(
                collection_name=collection_name,
                points=points
            )
    
    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        collection_name: str = "device_documents",
        filters: Optional[Dict[str, Any]] = None,
        dense_weight: float = 0.7,
        sparse_weight: float = 0.3
    ) -> List[RetrievalResult]:
        """
        Hybrid retrieval combining dense and sparse methods.
        
        This method implements the core hybrid retrieval functionality from Section 3.
        It performs both dense (semantic) and sparse (keyword) retrieval, then combines
        the results using weighted fusion.
        
        Process:
        1. Embed query using OpenAI (dense vector)
        2. Search Qdrant for similar vectors (dense retrieval)
        3. Search BM25 index for keyword matches (sparse retrieval)
        4. Combine scores using weighted fusion
        5. Return top-k results sorted by combined score
        
        Args:
            query: Query string (e.g., "blood glucose monitor")
            top_k: Number of results to return
            collection_name: Qdrant collection name
            filters: Optional metadata filters (e.g., device_class, year)
            dense_weight: Weight for dense retrieval score (default 0.7 = 70%)
            sparse_weight: Weight for sparse retrieval score (default 0.3 = 30%)
            
        Returns:
            List of RetrievalResult objects sorted by combined relevance score
        
        Reference: requirement doc - Section 3: "For hybrid search, combine both scores
                   (e.g., via weighted sum or Reciprocal Rank Fusion)"
        Reference: requirement doc - Section 3: "Qdrant queries both dense (vector similarity)
                   and sparse (keyword overlap) fields"
        """
        # Dense retrieval
        query_embedding = self.embed_text(query)
        
        # Build Qdrant filter
        qdrant_filter = None
        if filters:
            conditions = []
            for key, value in filters.items():
                conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value))
                )
            if conditions:
                qdrant_filter = Filter(must=conditions)
        
        dense_results = self.client.search(
            collection_name=collection_name,
            query_vector=query_embedding,
            limit=top_k * 2,  # Get more for reranking
            query_filter=qdrant_filter
        )
        
        # Sparse retrieval (BM25)
        sparse_scores = {}
        if collection_name in self.bm25_indexes:
            tokenized_query = query.lower().split()
            bm25_scores = self.bm25_indexes[collection_name].get_scores(tokenized_query)
            
            for i, chunk in enumerate(self.bm25_documents[collection_name]):
                # Normalize BM25 score to 0-1 range
                normalized_score = min(1.0, bm25_scores[i] / 10.0) if bm25_scores[i] > 0 else 0.0
                sparse_scores[chunk.chunk_id] = normalized_score
        
        # Combine scores
        combined_results = {}
        
        for result in dense_results:
            chunk_id = str(result.id)
            dense_score = result.score
            sparse_score = sparse_scores.get(chunk_id, 0.0)
            
            # Combined score
            combined_score = (dense_weight * dense_score) + (sparse_weight * sparse_score)
            
            combined_results[chunk_id] = {
                "chunk_id": chunk_id,
                "content": result.payload.get("content", ""),
                "score": combined_score,
                "dense_score": dense_score,
                "sparse_score": sparse_score,
                "metadata": {k: v for k, v in result.payload.items() if k != "content"},
                "document_id": result.payload.get("document_id", "")
            }
        
        # Sort by combined score and return top_k
        sorted_results = sorted(
            combined_results.values(),
            key=lambda x: x["score"],
            reverse=True
        )[:top_k]
        
        return [
            RetrievalResult(
                chunk_id=r["chunk_id"],
                content=r["content"],
                score=r["score"],
                metadata=r["metadata"],
                document_id=r["document_id"]
            )
            for r in sorted_results
        ]


class SemanticChunker:
    """
    Semantic-aware chunking for better context preservation.
    
    This class implements the "Semantic Chunking" improvement from Section 3.
    Instead of fixed-size chunks, it uses paragraph-based chunking to preserve
    semantic coherence and context.
    
    Why Semantic Chunking (from Section 3):
    - Fixed-size chunks can break sentences/paragraphs mid-thought
    - Semantic chunking preserves topic boundaries
    - Reduces noise from irrelevant text within chunks
    - Improves embedding quality by preserving context
    
    Implementation:
    - Split by paragraphs first (natural boundaries)
    - Merge paragraphs until chunk size is reached
    - Maintain overlap between chunks for context preservation
    
    Reference: requirement doc - Section 3: "Advanced Chunking Strategy: Instead of fixed-length
               chunks, use semantic-aware chunking—break documents into meaningful sections,
               like paragraphs or based on topic boundaries detected via NLP tools"
    Reference: requirement doc - Section 3: "This reduces noise from irrelevant text within
               chunks and improves embedding quality"
    """
    
    def __init__(self, chunk_size: int = 400, chunk_overlap: int = 50):
        """
        Initialize semantic chunker.
        
        Args:
            chunk_size: Target chunk size in characters (default 400, matching Section 3)
            chunk_overlap: Overlap between chunks in characters (preserves context)
            
        Reference: requirement doc - Section 3: "Chunk each document in fixed 300-400 long segments"
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def chunk_document(
        self,
        document_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        """
        Chunk document into semantically meaningful segments.
        
        This method implements semantic chunking by:
        1. Splitting content by paragraphs (natural boundaries)
        2. Merging paragraphs until chunk size is reached
        3. Maintaining overlap between chunks
        4. Preserving context and topic coherence
        
        Args:
            document_id: Document ID
            content: Document content to chunk
            metadata: Optional metadata to attach to chunks
            
        Returns:
            List of DocumentChunk objects with semantic boundaries preserved
        
        Reference: requirement doc - Section 3: "Process each document by segmenting into
                   meaningful paragraphs or sections using NLP tools like spaCy or
                   Sentence Transformers"
        Reference: requirement doc - Section 3: "Dynamically merge or split chunks based on
                   cosine similarity thresholds to preserve contextual coherence"
        """
        chunks = []
        metadata = metadata or {}
        
        # Split by paragraphs first
        paragraphs = content.split('\n\n')
        current_chunk = ""
        chunk_index = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # If adding this paragraph would exceed chunk size, finalize current chunk
            if current_chunk and len(current_chunk) + len(para) > self.chunk_size:
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{document_id}_chunk_{chunk_index}",
                        document_id=document_id,
                        content=current_chunk.strip(),
                        metadata=metadata,
                        chunk_index=chunk_index
                    )
                )
                chunk_index += 1
                # Start new chunk with overlap
                overlap_text = current_chunk[-self.chunk_overlap:] if len(current_chunk) > self.chunk_overlap else ""
                current_chunk = overlap_text + para
            else:
                current_chunk += "\n\n" + para if current_chunk else para
        
        # Add final chunk
        if current_chunk.strip():
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document_id}_chunk_{chunk_index}",
                    document_id=document_id,
                    content=current_chunk.strip(),
                    metadata=metadata,
                    chunk_index=chunk_index
                )
            )
        
        return chunks

