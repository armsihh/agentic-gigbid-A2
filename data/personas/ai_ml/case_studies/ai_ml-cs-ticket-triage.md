---
{"id": "ai_ml-cs-ticket-triage", "type": "case_study", "persona": "ai_ml", "project": "ticket-triage", "skills": ["Natural Language Processing", "Python Scikit-Learn", "Machine Learning", "Python"], "date": "2024-11-01", "client_industry": "SaaS", "synthetic": true}
---
# Support ticket triage classifier

**Client:** a UK SaaS helpdesk company  
**Industry:** SaaS  
**Year:** 2024

## The problem
Agents spent ~2 hours a day routing 4,000 weekly tickets into 14 queues by hand.

## What I did
Fine-tuned a DistilBERT classifier on 38k historical tickets, kept a TF-IDF + logistic regression fallback for low-confidence cases, and exposed it behind an internal API.

## Outcome
Routed 81% of tickets automatically at 94% precision; manual routing time fell by about 70%.

**Skills:** Natural Language Processing, Python Scikit-Learn, Machine Learning, Python
