#!/usr/bin/env python3
"""
Migration script: SQLite → PostgreSQL for Oracle Cloud deployment.

Usage:
    python migrate_to_postgres.py <source_db> <target_db_url>

Example:
    python migrate_to_postgres.py /tmp/alerts.db postgresql://user:pass@host:5432/discord_bot
"""
import sqlite3
import psycopg2
import json
import sys
from datetime import datetime

def migrate_sqlite_to_postgres(sqlite_path, postgres_url):
    """Migrate data from SQLite to PostgreSQL."""
    
    print(f"📊 Starting migration from {sqlite_path} to PostgreSQL...")
    
    # Connect to SQLite
    try:
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        print("✅ Connected to SQLite")
    except Exception as e:
        print(f"❌ Failed to connect to SQLite: {e}")
        return False
    
    # Connect to PostgreSQL
    try:
        postgres_conn = psycopg2.connect(postgres_url)
        postgres_cursor = postgres_conn.cursor()
        print("✅ Connected to PostgreSQL")
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return False
    
    tables = ["alerts", "trades", "portfolio", "command_log", "user_watchlists", "ibkr_config"]
    
    try:
        for table in tables:
            print(f"\n📋 Migrating table: {table}")
            
            # Get data from SQLite
            sqlite_cursor.execute(f"SELECT * FROM {table}")
            rows = sqlite_cursor.fetchall()
            
            if not rows:
                print(f"   ℹ️  No data in {table}")
                continue
            
            # Get column names
            columns = [description[0] for description in sqlite_cursor.description]
            
            # Insert into PostgreSQL
            for row in rows:
                placeholders = ", ".join(["%s"] * len(columns))
                col_names = ", ".join(columns)
                sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                
                try:
                    postgres_cursor.execute(sql, row)
                except psycopg2.IntegrityError:
                    # Skip duplicates
                    pass
                except Exception as e:
                    print(f"   ⚠️  Error inserting row: {e}")
            
            postgres_conn.commit()
            print(f"   ✅ Migrated {len(rows)} rows")
        
        print("\n✅ Migration completed successfully!")
        print("\n📝 Next steps:")
        print("   1. Test your application with the new PostgreSQL database")
        print("   2. Verify all data is present and correct")
        print("   3. Deploy to Oracle Cloud with DATABASE_URL pointing to PostgreSQL")
        print("   4. Archive the old SQLite file as backup")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        postgres_conn.rollback()
        return False
    
    finally:
        sqlite_conn.close()
        postgres_conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python migrate_to_postgres.py <sqlite_path> <postgres_url>")
        print("\nExample:")
        print("  python migrate_to_postgres.py /tmp/alerts.db postgresql://user:pass@oracle-host:5432/discord_bot")
        sys.exit(1)
    
    sqlite_path = sys.argv[1]
    postgres_url = sys.argv[2]
    
    success = migrate_sqlite_to_postgres(sqlite_path, postgres_url)
    sys.exit(0 if success else 1)
