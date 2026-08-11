import sqlite3

conn = sqlite3.connect("database.db")

conn.execute(
    """
    UPDATE admin
    SET permissions = '["books","issue","return"]'
    WHERE username = 'worker'
    """
)

conn.commit()
conn.close()

print("Worker permissions updated")
