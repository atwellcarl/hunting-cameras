"""Manage Buck Book crew accounts (runs on this Mac with the Supabase secret key).

Each crew member signs in with their name and a password you give them. Behind
the scenes the name maps to a placeholder address <name>@buckbook.invalid, which
can never receive mail, so no real email addresses are needed.

Commands:
  add "Name"      Create an account and print a new password to hand over.
  reset "Name"    Print a fresh password for an existing account.
  remove "Name"   Delete the account. Their labels stay, still credited by name.
  list            Show crew and when each last signed in.

Usage: .venv/bin/python -m buckbook.crew_admin add "Big Mike"
"""
import re
import secrets
import sys

from buckbook.supabase_sync import call, rest

DOMAIN = "buckbook.invalid"
# Short outdoors words: passwords read like "scrape-oak-ridge-draw-47".
WORDS = """acorn antler ash aspen bank bark basin bench birch bluff bottom brush buck
cedar clover creek crest cut doe draw fawn fern field flat fog frost gap glade grass
hazel hill hollow knob larch leaf ledge maple marsh meadow moss oak pine plot pond
rack rain ridge rub run saddle scrape sedge shed slope snow spruce spur stand stump
swamp tine track trail vale willow wind""".split()


def slug(name):
    return re.sub(r"[^a-z0-9]+", ".", name.strip().lower()).strip(".")


def email_for(name):
    s = slug(name)
    if not s:
        raise SystemExit("Name needs at least one letter or number.")
    return f"{s}@{DOMAIN}"


def new_password():
    return "-".join(secrets.choice(WORDS) for _ in range(4)) + f"-{secrets.randbelow(90) + 10}"


def find_user(name):
    target = email_for(name)
    page = 1
    while True:
        status, out = call("GET", f"/auth/v1/admin/users?page={page}&per_page=200")
        if status >= 300:
            raise SystemExit(f"Listing accounts failed (HTTP {status}): {out}")
        users = out.get("users", [])
        for u in users:
            if u.get("email") == target:
                return u
        if len(users) < 200:
            return None
        page += 1


def add(name):
    name = name.strip()
    if len(name) > 30:
        raise SystemExit("Keep names to 30 characters or fewer.")
    if find_user(name):
        raise SystemExit(f"{name!r} already has an account. Use `reset` for a new password.")
    password = new_password()
    status, user = call("POST", "/auth/v1/admin/users",
                        {"email": email_for(name), "password": password, "email_confirm": True,
                         "user_metadata": {"name": name}})
    if status >= 300:
        raise SystemExit(f"Creating the account failed (HTTP {status}): {user}")
    rest("POST", "crew", {"user_id": user["id"], "name": name}, prefer="resolution=merge-duplicates")
    print(f"Added {name}.\n  Sign in as: {name}\n  Password:   {password}\n"
          "Give them the password privately. It isn't stored anywhere you can look it up later.")


def reset(name):
    user = find_user(name)
    if not user:
        raise SystemExit(f"No account for {name!r}. Use `add` to create one.")
    password = new_password()
    status, out = call("PUT", f"/auth/v1/admin/users/{user['id']}", {"password": password})
    if status >= 300:
        raise SystemExit(f"Resetting the password failed (HTTP {status}): {out}")
    print(f"New password for {name}: {password}")


def remove(name):
    user = find_user(name)
    if not user:
        raise SystemExit(f"No account for {name!r}.")
    status, out = call("DELETE", f"/auth/v1/admin/users/{user['id']}")
    if status >= 300:
        raise SystemExit(f"Removing the account failed (HTTP {status}): {out}")
    print(f"Removed {name}. Their labels stay in the book.")


def list_crew():
    crew = {c["user_id"]: c["name"] for c in rest("GET", "crew", query="?select=user_id,name")}
    status, out = call("GET", "/auth/v1/admin/users?per_page=200")
    last = {u["id"]: (u.get("last_sign_in_at") or "never")[:16].replace("T", " ") for u in out.get("users", [])}
    if not crew:
        print("No crew yet. Add someone with: add \"Name\"")
    for uid, name in sorted(crew.items(), key=lambda kv: kv[1].lower()):
        print(f"  {name:<24} last sign-in: {last.get(uid, 'unknown')}")


if __name__ == "__main__":
    cmd, arg = (sys.argv + ["", ""])[1:3]
    if cmd == "add" and arg:
        add(arg)
    elif cmd == "reset" and arg:
        reset(arg)
    elif cmd == "remove" and arg:
        remove(arg)
    elif cmd == "list":
        list_crew()
    else:
        raise SystemExit(__doc__)
