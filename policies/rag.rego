package rag.authz

default allow = false

allow {
  input.resource.collection == "hr"
  input.user.groups[_] == "hr"
}

allow {
  input.resource.collection == "compliance"
  input.user.groups[_] == "compliance"
}

allow {
  input.resource.collection == "finance"
  input.user.groups[_] == "finance"
}

allow {
  input.resource.collection == "bt"
  input.user.groups[_] == "bt"
}

allow {
  input.resource.collection == "risk"
  input.user.groups[_] == "risk"
}

allow {
  input.resource.collection == "hukuk"
  input.user.groups[_] == "hukuk"
}
