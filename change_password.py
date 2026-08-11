from werkzeug.security import generate_password_hash
import database as db

username = "worker"       # change username here
new_password = "worker123"  # set your new password here

conn = db.get_connection()

hashed = generate_password_hash(new_password)

conn.execute(
    "UPDATE admin SET password = ? WHERE username = ?",
    (hashed, username)
)

conn.commit()
conn.close()

print("Password changed successfully")
print("Username:", username)
print("New password:", new_password)