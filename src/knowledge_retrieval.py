"""
Knowledge retrieval system for global and client-specific knowledge.

This module implements Section 4 of the requirement doc: "Knowledge Retrieval".

The knowledge retrieval system provides context-aware information for agents by maintaining
two separate knowledge stores:
1. Global (Consultant) Knowledge: FDA guidelines, regulatory best practices, etc.
2. Client Knowledge: Client-specific information (conversations, meetings, device info)

Key Design Principles (from Section 4):
- Dual Knowledge Stores: Separate stores for global vs client-specific knowledge
- Parsing and Vectorization: Ingest conversations and extract knowledge chunks
- Storage & Indexing: Vector database with multi-namespace support
- Retrieval Layer: Query both stores with metadata filtering
- Handling Redundancy: Timestamp-based versioning and conflict detection
- Continuous Updates: Incremental ingestion and conflict resolution

Example from Section 4:
- "clinical trial starting early 2026" (client info)
- "trial involves 100 participants" (client info)
- "One should not ask FDA open-ended questions for presubmission" (global info)

Reference: requirement doc - Section 4: Knowledge Retrieval
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from openai import OpenAI
from src.config import settings
from src.models import KnowledgeChunk, KnowledgeType


class KnowledgeRetrieval:
    """
    Knowledge retrieval system with dual stores (global + client).
    
    This class implements the "Dual Knowledge Stores" architecture from Section 4.
    It maintains separate vector stores for global (consultant) knowledge and
    client-specific knowledge, allowing agents to retrieve context-aware information.
    
    Key Features (from Section 4):
    - Global Knowledge: Centralized, static or slowly evolving corpus (FDA guidelines, etc.)
    - Client Knowledge: Dynamic, scoped to each client, continuously updated from conversations
    - Metadata Filtering: Filter by client_id, source, timestamp, confidence
    - Recency Scoring: Newer information has higher relevance
    - Conflict Detection: Identify contradictory information
    
    Reference: requirement doc - Section 4: "1. Dual Knowledge Stores:
               Global (Consultant) Knowledge: Centralized, static or slowly evolving corpus
               (e.g., FDA guidelines, regulatory best practices) accessible across all clients"
    Reference: requirement doc - Section 4: "Client Knowledge Store: Dynamic, scoped to each
               client or organization, continuously updated from parsed conversations"
    """
    
    def __init__(self):
        """
        Initialize knowledge retrieval system.
        
        Sets up connections to Qdrant for both global and client knowledge stores.
        Creates separate collections for isolation between global and client knowledge.
        
        Reference: requirement doc - Section 4: "Use vector search database (such as Qdrant
                   or Pinecone) with capacity for: Multi-namespace or multi-collection
                   support to isolate client vs global knowledge bases"
        """
        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key
        )
        self.openai_client = OpenAI(api_key=settings.openai_api_key)
        
        # Initialize collections
        self._ensure_collections()
    
    def _ensure_collections(self):
        """Ensure Qdrant collections exist for knowledge stores."""
        collections = ["global_knowledge", "client_knowledge"]
        
        for collection_name in collections:
            try:
                self.client.get_collection(collection_name)
            except Exception:
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=1536,
                        distance=Distance.COSINE
                    )
                )
    
    def embed_text(self, text: str) -> List[float]:
        """Generate embedding using OpenAI."""
        response = self.openai_client.embeddings.create(
            model=settings.embedding_model,
            input=text
        )
        return response.data[0].embedding
    
    def index_knowledge_chunk(self, chunk: KnowledgeChunk):
        """
        Index a knowledge chunk in the appropriate store.
        
        Args:
            chunk: Knowledge chunk to index
        """
        collection_name = (
            "global_knowledge" if chunk.knowledge_type == KnowledgeType.GLOBAL 
            else "client_knowledge"
        )
        
        if not chunk.embedding:
            chunk.embedding = self.embed_text(chunk.content)
        
        point = PointStruct(
            id=chunk.chunk_id,
            vector=chunk.embedding,
            payload={
                "content": chunk.content,
                "knowledge_type": chunk.knowledge_type.value,
                "client_id": chunk.client_id,
                "source": chunk.source,
                "timestamp": chunk.timestamp.isoformat(),
                "confidence": chunk.confidence,
                **chunk.metadata
            }
        )
        
        self.client.upsert(
            collection_name=collection_name,
            points=[point]
        )
    
    def retrieve(
        self,
        query: str,
        client_id: Optional[str] = None,
        top_k: int = 10,
        include_global: bool = True,
        include_client: bool = True,
        min_confidence: float = 0.0,
        recency_weight: float = 0.3
    ) -> List[KnowledgeChunk]:
        """
        Retrieve knowledge chunks relevant to query.
        
        Args:
            query: Query string
            client_id: Optional client ID for filtering
            top_k: Number of results per store
            include_global: Include global knowledge
            include_client: Include client-specific knowledge
            min_confidence: Minimum confidence threshold
            recency_weight: Weight for recency in scoring
            
        Returns:
            List of knowledge chunks sorted by relevance
        """
        query_embedding = self.embed_text(query)
        results = []
        
        # Retrieve from global knowledge
        if include_global:
            global_results = self.client.search(
                collection_name="global_knowledge",
                query_vector=query_embedding,
                limit=top_k
            )
            
            for result in global_results:
                payload = result.payload
                if payload.get("confidence", 1.0) >= min_confidence:
                    chunk = KnowledgeChunk(
                        chunk_id=str(result.id),
                        content=payload["content"],
                        knowledge_type=KnowledgeType.GLOBAL,
                        client_id=None,
                        source=payload.get("source", "unknown"),
                        timestamp=datetime.fromisoformat(payload["timestamp"]),
                        confidence=payload.get("confidence", 1.0),
                        metadata={k: v for k, v in payload.items() 
                                if k not in ["content", "knowledge_type", "client_id", 
                                           "source", "timestamp", "confidence"]},
                        embedding=result.vector
                    )
                    # Adjust score with recency
                    recency_score = self._calculate_recency_score(chunk.timestamp)
                    adjusted_score = (1 - recency_weight) * result.score + recency_weight * recency_score
                    results.append((adjusted_score, chunk))
        
        # Retrieve from client knowledge
        if include_client and client_id:
            client_filter = Filter(
                must=[
                    FieldCondition(key="client_id", match=MatchValue(value=client_id))
                ]
            )
            
            client_results = self.client.search(
                collection_name="client_knowledge",
                query_vector=query_embedding,
                query_filter=client_filter,
                limit=top_k
            )
            
            for result in client_results:
                payload = result.payload
                if payload.get("confidence", 1.0) >= min_confidence:
                    chunk = KnowledgeChunk(
                        chunk_id=str(result.id),
                        content=payload["content"],
                        knowledge_type=KnowledgeType.CLIENT,
                        client_id=payload.get("client_id"),
                        source=payload.get("source", "unknown"),
                        timestamp=datetime.fromisoformat(payload["timestamp"]),
                        confidence=payload.get("confidence", 1.0),
                        metadata={k: v for k, v in payload.items() 
                                if k not in ["content", "knowledge_type", "client_id", 
                                           "source", "timestamp", "confidence"]},
                        embedding=result.vector
                    )
                    # Adjust score with recency (client knowledge is typically more recent)
                    recency_score = self._calculate_recency_score(chunk.timestamp)
                    adjusted_score = (1 - recency_weight) * result.score + recency_weight * recency_score
                    results.append((adjusted_score, chunk))
        
        # Sort by combined score and deduplicate
        results.sort(key=lambda x: x[0], reverse=True)
        
        # Deduplicate similar chunks
        seen_content = set()
        unique_chunks = []
        for score, chunk in results:
            content_hash = hash(chunk.content[:100])  # Hash first 100 chars
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_chunks.append(chunk)
        
        return unique_chunks[:top_k * 2]  # Return top results from both stores
    
    def _calculate_recency_score(self, timestamp: datetime) -> float:
        """Calculate recency score (0-1) based on timestamp."""
        now = datetime.now()
        age_days = (now - timestamp).days
        
        # Decay function: newer = higher score
        # Score decays to 0.5 after 30 days, 0.1 after 90 days
        if age_days <= 7:
            return 1.0
        elif age_days <= 30:
            return 1.0 - (age_days - 7) / 46  # Linear decay from 1.0 to 0.5
        elif age_days <= 90:
            return 0.5 - (age_days - 30) / 120  # Linear decay from 0.5 to 0.1
        else:
            return max(0.1, 1.0 - age_days / 365)  # Slow decay after 90 days
    
    def detect_conflicts(
        self,
        chunks: List[KnowledgeChunk],
        threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Detect conflicting information in knowledge chunks.
        
        Args:
            chunks: List of knowledge chunks
            threshold: Similarity threshold for conflict detection
            
        Returns:
            List of detected conflicts
        """
        conflicts = []
        
        # Simple conflict detection: check for contradictory statements
        # In production, use more sophisticated NLP models
        for i, chunk1 in enumerate(chunks):
            for chunk2 in chunks[i+1:]:
                # Check if chunks are about same topic but have different information
                if chunk1.knowledge_type != chunk2.knowledge_type:
                    # Compare embeddings for similarity
                    if chunk1.embedding and chunk2.embedding:
                        similarity = self._cosine_similarity(
                            chunk1.embedding,
                            chunk2.embedding
                        )
                        
                        if similarity > threshold:
                            # Potential conflict - same topic, different sources/types
                            conflicts.append({
                                "chunk1": chunk1.chunk_id,
                                "chunk2": chunk2.chunk_id,
                                "similarity": similarity,
                                "type1": chunk1.knowledge_type,
                                "type2": chunk2.knowledge_type,
                                "timestamp1": chunk1.timestamp,
                                "timestamp2": chunk2.timestamp
                            })
        
        return conflicts
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import numpy as np
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

