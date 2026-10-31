from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_postgres import PGVector
from sqlalchemy import delete
from typing_extensions import List


class DocumentRepository:
    def __init__(self, db_url: str):
        self.search_type = "similarity"
        self.db_url = f"{db_url}"

    def add(
        self,
        embeddings_model: Embeddings,
        collection_name: str,
        documents: List[Document],
        *,
        schema: str,
    ):
        vector_store = self.get_vector_store(embeddings_model, collection_name, schema)
        vector_store.add_documents(documents)

    def search(
        self,
        embeddings_model: Embeddings,
        collection_name: str,
        query: str,
        size: int = 5,
        *,
        schema: str,
    ):
        vector_store = self.get_vector_store(embeddings_model, collection_name, schema)
        return vector_store.search(query, self.search_type, k=size)

    def delete_by_attachment(
        self,
        embeddings_model: Embeddings | None,
        collection_name: str,
        attachment_id: str,
        *,
        schema: str,
        keep_ids: List[str] = (),
    ):
        # PGVector.delete only accepts ids, so filter on chunk metadata here;
        # keep_ids spares the chunks just written by a re-embedding.
        vector_store = self.get_vector_store(embeddings_model, collection_name, schema)
        embedding_store = vector_store.EmbeddingStore
        with vector_store.session_maker() as session:
            collection = vector_store.get_collection(session)
            if collection is None:
                return
            session.execute(
                delete(embedding_store).where(
                    embedding_store.collection_id == collection.uuid,
                    embedding_store.cmetadata["attachment_id"].astext == attachment_id,
                    embedding_store.id.not_in(keep_ids),
                )
            )
            session.commit()

    def get_vector_store(
        self,
        embeddings_model: Embeddings,
        collection_name: str,
        schema: str,
    ) -> VectorStore:
        # Collections live in one shared vectors database; the tenant schema
        # prefix keeps each tenant's chunks apart. "/" cannot occur in a schema
        # name, so two (schema, collection) pairs never map to the same name.
        return PGVector(
            embeddings=embeddings_model,
            collection_name=f"{schema}/{collection_name}",
            connection=self.db_url,
            use_jsonb=True,
        )
