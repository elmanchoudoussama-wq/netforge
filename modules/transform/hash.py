import hashlib
pw = "YOUR_REAL_PASSWORD"          # the password you actually typed

sessions = [
    ("201620124591367041864809", "ec161bba4e39cc0550e6e2a5f66b6974ad41604201cf2cb5735a15db7fd9de40"),
    ("155966679094482688242208", "d7908230aea345ba57dd9a478b45780d85b59efcff467c921b9840e00f082c7a"),
]

def h(s): return hashlib.sha256(s.encode()).hexdigest()

schemes = {
    "sha256(pw)":            lambda pw,t: h(pw),
    "sha256(pw+token)":      lambda pw,t: h(pw + t),
    "sha256(token+pw)":      lambda pw,t: h(t + pw),
    "sha256(pw+':'+token)":  lambda pw,t: h(pw + ":" + t),
    "sha256(token+':'+pw)":  lambda pw,t: h(t + ":" + pw),
    "sha256(pw+token+pw)":   lambda pw,t: h(pw + t + pw),
}

for name, fn in schemes.items():
    ok = all(fn(pw, tok) == target for tok, target in sessions)
    print(("✅ MATCH  " if ok else "   no     ") + name)
