"""Fresh snapshot schema, built offline then opened read-only."""
'''
papers:DBLP-key,title,year,venue,doi,record_url,urls(序列化的多个外链),authors_json,content_hash(这条记录的hash)

authors:identity(规范化后的名字,没完全看)，name,pid

paper_authors : 主键(paper_id,position)。
metadata:元数据

FST5全文索引
paper_fts：title, authors_text, venue，tokenize='unicode61 remove_diacritics 2'
author_fts：name, tokenize='unicode61 remove_diacritics 2'

'''
import sqlite3

SCHEMA = """
PRAGMA journal_mode=DELETE;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=FILE;
PRAGMA cache_size=-65536;
CREATE TABLE papers (
 id INTEGER PRIMARY KEY, dblp_key TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL, year INTEGER, venue TEXT, doi TEXT,
 record_url TEXT NOT NULL, urls TEXT NOT NULL, authors_json TEXT NOT NULL,
 content_hash TEXT NOT NULL
);
CREATE TABLE authors (
 id INTEGER PRIMARY KEY, identity TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL, pid TEXT
);
CREATE TABLE paper_authors (
 paper_id INTEGER NOT NULL, author_id INTEGER NOT NULL, position INTEGER NOT NULL,
 PRIMARY KEY(paper_id, position)
);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE VIRTUAL TABLE paper_fts USING fts5(title, authors_text, venue,
 tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE author_fts USING fts5(name, tokenize='unicode61 remove_diacritics 2');
"""

INDEXES = """
CREATE INDEX paper_year ON papers(year);
CREATE INDEX paper_doi ON papers(doi);
CREATE INDEX paper_venue ON papers(venue);
CREATE INDEX paper_authors_author ON paper_authors(author_id, paper_id);
CREATE INDEX authors_pid ON authors(pid);
"""


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
