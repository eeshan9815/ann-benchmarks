# License: https://github.com/erikbern/ann-benchmarks/blob/main/LICENSE

import subprocess
import sys

import pgvector.psycopg
import psycopg

from ..base.module import BaseANN


class PGVector(BaseANN):
    def __init__(self, metric, method_param):
        self._metric = metric
        self._m = method_param["M"]
        self._ef_construction = method_param["efConstruction"]
        self._cur = None

        if metric == "angular":
            self._query = "SELECT id FROM items ORDER BY embedding <=> %s LIMIT %s"
        elif metric == "euclidean":
            self._query = "SELECT id FROM items ORDER BY embedding <-> %s LIMIT %s"
        else:
            raise RuntimeError(f"unknown metric {metric}")

    def fit(self, X):
        conn = psycopg.connect(host = "10.33.0.9", user="super", password="12", dbname="ann", autocommit=True)
        pgvector.psycopg.register_vector(conn)
        cur = conn.cursor()
        self._cur = cur
        cur.execute("CREATE TABLE IF NOT EXISTS items (id int, embedding vector(%d))" % X.shape[1])
        cur.execute("ALTER TABLE items ALTER COLUMN embedding SET STORAGE PLAIN")
        print("copying data...")
        with cur.copy("COPY items (id, embedding) FROM STDIN") as copy:
            for i, embedding in enumerate(X):
                copy.write_row((i, embedding))
        print("creating index...")
        cur.execute("SET min_parallel_table_scan_size TO 1")
        if self._metric == "angular":
            cur.execute(
                "CREATE INDEX ON items USING hnsw (embedding vector_cosine_ops) WITH (m = %s, ef_construction = %d)" % (self._m, self._ef_construction)
            )
        elif self._metric == "euclidean":
            cur.execute("CREATE INDEX ON items USING hnsw (embedding vector_l2_ops) WITH (m = %s, ef_construction = %d)" % (self._m, self._ef_construction))
        else:
            raise RuntimeError(f"unknown metric {self._metric}")
        cur.execute("RESET min_parallel_table_scan_size")
        print("vacuum and checkpoint")
        cur.execute("VACUUM ANALYZE items;")
        cur.execute("CHECKPOINT;")
        print("warm cache")
        cur.execute("SELECT pg_prewarm('items')")
        cur.execute("SELECT pg_prewarm('items_embedding_idx')")
        print("done!")

    def set_query_arguments(self, ef_search):
        self._ef_search = ef_search
        self._cur.execute("SET hnsw.ef_search = %d" % ef_search)
        self._cur.execute("SET work_mem = '4GB'")

    def query(self, v, n):
        self._cur.execute(self._query, (v, n), binary=True, prepare=True)
        return [id for id, in self._cur.fetchall()]

    def get_memory_usage(self):
        if self._cur is None:
            return 0
        self._cur.execute("SELECT pg_relation_size('items_embedding_idx')")
        return self._cur.fetchone()[0] / 1024

    def done(self):
        self._cur.execute("DROP TABLE items")
        self._cur.close()

    def __str__(self):
        return f"PGVectorHNSW(m={self._m}, ef_construction={self._ef_construction}, ef_search={self._ef_search})"
