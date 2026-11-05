# Questions written before looking at the corpus. `rfc` is the document that
# should authoritatively answer it, named from the domain, not from search.
# `expect` is a string the answer must contain for the answer to be correct.

ANSWERABLE = [
    ("What is the maximum length of a single DNS label?",          1035, "63"),
    ("What is the maximum length of a full domain name?",          1035, "255"),
    ("How large can a DNS message over UDP be without EDNS?",      1035, "512"),
    ("Which port does DNS use?",                                   1035, "53"),
    ("Is DNS case sensitive?",                                     1035, "insensitive"),
    ("What is a CNAME record?",                                    1034, "alias"),
    ("What does the TTL field control?",                           1035, "cach"),
    ("What does NXDOMAIN mean?",                                   8020, "not exist"),
    ("What does the TC bit in a DNS header mean?",                 2181, "truncat"),
    ("What is stored in a SOA record?",                            1035, "serial"),
    ("What is a glue record?",                                     9471, "address"),
    ("What is a stub resolver?",                                   1034, "resolver"),
    ("What is an AXFR zone transfer?",                             5936, "zone"),
    ("What is an IXFR zone transfer?",                             1995, "increment"),
    ("How does negative caching work in DNS?",                     2308, "negative"),
    ("How do wildcard records work?",                              4592, "wildcard"),
    ("What is DNS message compression?",                           1035, "pointer"),
    ("What is EDNS(0)?",                                           6891, "OPT"),
    ("What does DNSSEC protect against?",                          4033, "authentic"),
    ("What is an NSEC record?",                                    4034, "next"),

    # topics the old graph-derived corpus could not answer at all
    ("What is DNS over HTTPS?",                                    8484, "HTTP"),
    ("Which port does DNS over TLS use?",                          7858, "853"),
    ("What is DNS over QUIC?",                                     9250, "QUIC"),
    ("What is NSEC3 and why does it exist?",                       5155, "hash"),
    ("What is EDNS Client Subnet?",                                7871, "subnet"),
    ("What is an SVCB record?",                                    9460, "service"),
    ("What is Multicast DNS?",                                     6762, "multicast"),
    ("What is a TLSA record used for?",                            6698, "certificat"),
    ("What are Extended DNS Errors?",                              8914, "error"),
    ("What is DNS-based Service Discovery?",                       6763, "service"),
]

UNANSWERABLE = [
    "How do I configure BIND9?",
    "Why is my website slow?",
    "Which DNS provider should I use?",
    "What is the capital of France?",
    "How do I install Ubuntu?",
    "Write me a Python script to query DNS",
    "What is the best pizza topping?",
    "How much does Cloudflare cost?",
    "How do I renew my TLS certificate?",
    "What is the price of Route 53?",
]
