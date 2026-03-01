package rag.authz

default allow = false

allow {
  input.resource.collection == "hr"
  input.user.roles[_] == "hr"
}

allow {
  input.resource.collection == "compliance"
  input.user.roles[_] == "compliance"
}

allow {
  input.resource.collection == "finance"
  input.user.roles[_] == "finance"
}
