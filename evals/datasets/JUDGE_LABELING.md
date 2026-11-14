# Judge calibration: label 30 proposals

Score each proposal **1-5 overall**, using the same rubric as the LLM judge:
relevance to the job, specificity (concrete projects and numbers), grounding (believable, nothing invented),
clarity (readable, right length, clear next step). 1 = would never send, 3 = okay, 5 = excellent.

Write your scores in `evals/datasets/judge_labels.csv` (second column). Don't look at the judge's scores first.

## 1. `v0_naive:job-01ce9333d8`
**Job:** Lead Machine Learning Engineer - Voice Cloning and Text-to-Speech Development

> We are seeking a highly skilled Machine Learning Engineer to join our team and lead the development of an AI application for our organization. The successful candidate will be responsible for creating a personal text-to-speech bot, paired with an avatar that closely resembles our CEO through the use of thousands of hours of audio recordings.

Key Responsibilities:

-Develop, test and deploy a mach

**Proposal:**

I’m excited to help you create a realistic CEO‑voice avatar for your organization. I have proposed building a voice‑cloning engine on top of Tortoise TTS, giving me a concrete roadmap for high‑fidelity voice synthesis. In a recent audio‑AI proof‑of‑concept I built an end‑to‑end pipeline that performed speech‑to‑text, speaker segmentation and LLM‑driven summarisation, showing I can handle the full audio processing stack. My work with TensorFlow and PyTorch on deep‑learning projects, plus experience fine‑tuning large language models such as DistilBERT, equips me to develop, test and deploy a robust TTS system. I will start by analysing the CEO’s audio corpus, training a speaker‑adaptive Tortoise model, and integrating the output with a 3‑D avatar using standard WebGL APIs. Continuous improvement will be driven by automated quality metrics and regular stakeholder reviews. Let’s schedule a short call to discuss the data pipeline and timeline.

---

## 2. `v0_naive:job-47e2165278`
**Job:** Help Wanted: Full Stack Engineer - Knowledge of Chat GPT

> We are seeking a highly skilled Chat GPT Developer to join our team and develop an EdTech website platform. The ideal candidate will have experience with natural language processing, machine learning, and web development.

Responsibilities:
*Develop and maintain a web site using the OpenAI API
*Integrate natural language processing and machine learning capabilities into the site
*Collaborate with 

**Proposal:**

Hi there — building an EdTech website platform with OpenAI API integration, NLP, and ML is exactly the kind of project I've been delivering. For a UK SaaS helpdesk company, I built a support ticket triage classifier that routed 81% of tickets automatically at 94% precision, cutting manual routing time by roughly 70%. That same pattern — training a model, exposing it behind an API, and wiring it into a live web product — is how I'd approach your EdTech platform: train or fine-tune models on

---

## 3. `v0_naive:job-7e98231709`
**Job:** Build a ruby sinatra app with a open AI chatbot

> Build a ruby app using the sinatra framework (I prefer a light weight framework), for parents of a daycare to check the progress reports of students and for teachers to enter progress report details. Progress report data will then need to be used train a chatbot that can answer parents questions about a childs growth and development.

**Proposal:**

You need a lightweight Ruby Sinatra web app that lets daycare parents view progress reports, lets teachers enter those reports, and powers an AI chatbot to answer parent questions about child development. I will create the required parent and teacher interfaces in Sinatra, connect them to a secure API, and train a custom NLP model on your progress‑report data to deliver reliable, development‑focused answers. Let’s schedule a brief call to confirm the data format and timeline.

---

## 4. `v0_naive:job-cc68d751c0`
**Job:** Solution Architect / Tech consultant - JS stack, part-time

> We're is looking for Solution Architects or Senior engineers to help during the exploration phase when launching new products.

NOTE: We aren't looking for DevOps or system admins. You need to be an experienced engineer (with at least 7 years of coding experience, back-end or full-stack, with AWS knowledge/certification ideally). You need to have experience either with MERN/MEAN.

The job is part-

**Proposal:**

You need a senior engineer to drive technical discussions, audit existing architectures, and facilitate stakeholder decisions during new product launches. I built a multi-tenant SaaS admin dashboard for a US property-management startup, onboarding 60 property companies in four months with page loads under 1.2 s at p95. The system used React, TypeScript, Next.js, and PostgreSQL, with role-based access, tenant isolation in every query, and server-side pagination. I also developed an API-integr

---

## 5. `v0_naive:job-01239d603b`
**Job:** Data analysis tracking stock changes (sales history) by a competitor

> Looking into a software which can track the history of stock values from one of my competitors.
The stock values are declared in the front end of the product page.
Need to be in a visualization (diagram) along with timestamp of when the changes was made, and when the product was created by the crawler.
The crawler needs to support proxies and multi thread.

Looking into a software for stock monito

**Proposal:**

You need a Python tool that daily scrapes competitor front-end code for stock values, prices, and options, visualizes inventory fluctuations with change and row-creation timestamps, and supports proxies, multi-threading, and sitemap-based URL discovery for three competitors. My closest relevant work is data analysis and visualization: I built a pricing-analysis model for a B2B packaging manufacturer that increased average gross margin

---

## 6. `ai_ml-prop-112`
**Job:** WordPress Plugin Developer(ChatGPT & OpenAI)

> Skills: WordPress Development, Plugin Development, ChatGPT, OpenAI Codex, WordPress Plugin, API Integration

**Proposal:**

You need wordpress development. Last year I built retrieval chatbot over legal contracts for a Dubai-based legal-tech startup, and answer accuracy on a 120-question test set rose from 58% to 86%; every answer links to its clause.

For this job I would built a hybrid retrieval pipeline (keyword + embeddings) with clause-level chunking and citation of the source page in every answer.

Relevant skills: ChatGPT, Chatbot Development, Natural Language Processing, API Integration. Happy to share more details on a call.

---

## 7. `ai_ml-prop-144`
**Job:** AI-Related Products Guest Post Writer

> Skills: Guest Post, Machine Learning, Data Science, Writing, English, Content Writing, Blog Content, SEO Writing

**Proposal:**

Hi - your post mentions guest post. I solved a very similar problem for a regional telecom operator: Top-decile lift of 3.4x; the retention campaign saved an estimated 1,100 subscribers in one quarter.

For this job I would engineered 60 usage features from billing SQL tables, compared logistic regression, random forest and gradient boosting, and explained predictions per customer.

Relevant skills: Machine Learning, Python Scikit-Learn, Data Science, Statistics. Happy to share more details on a call.

---

## 8. `ai_ml-prop-116`
**Job:** Pytorch Art-Based Style Transfer, Machine Learning App

> Skills: Python, Machine Learning

**Proposal:**

You need python. Last year I built support ticket triage classifier for a UK SaaS helpdesk company, and routed 81% of tickets automatically at 94% precision; manual routing time fell by about 70%.

For this job I would fine-tuned a DistilBERT classifier on 38k historical tickets, kept a TF-IDF + logistic regression fallback for low-confidence cases, and exposed it behind an internal API.

Relevant skills: Natural Language Processing, Python Scikit-Learn, Machine Learning, Python. Happy to share more details on a call.

---

## 9. `ai_ml-prop-128`
**Job:** Computer vision developer needed for AI project

> Skills: Computer Vision, Python, Machine Learning, Deep Learning, Neural Network, Image Processing, MATLAB, TensorFlow

**Proposal:**

Quick note on computer vision: in my visual defect detection on a bottling line project for a Faisalabad beverage manufacturer, recall on defects reached 96% at 2% false alarms; ran at 45 FPS on CPU.

For this job I would trained a YOLO-style detector on 6,200 labelled frames with heavy augmentation, exported to ONNX and ran it on an edge PC beside the conveyor.

Relevant skills: Computer Vision, Deep Learning, PyTorch, OpenCV. Happy to share more details on a call.

---

## 10. `ai_ml-prop-049`
**Job:** Train and deploy a custom ChatGPT model using OpenAI CLI

> Skills: Artificial Intelligence, Machine Learning, Deep Learning, Neural Network, Deep Learning Modeling

**Proposal:**

Hi - your post mentions artificial intelligence. I solved a very similar problem for a UK SaaS helpdesk company: Routed 81% of tickets automatically at 94% precision; manual routing time fell by about 70%.

For this job I would fine-tuned a DistilBERT classifier on 38k historical tickets, kept a TF-IDF + logistic regression fallback for low-confidence cases, and exposed it behind an internal API.

Relevant skills: Natural Language Processing, Python Scikit-Learn, Machine Learning, Python. Happy to share more details on a call.

---

## 11. `ai_ml-prop-045`
**Job:** PyTorch Developer

> Skills: PyTorch, Machine Learning, Deep Learning, Python, Neural Network

**Proposal:**

Hello, I have read your job post and I am the perfect fit for this job.

For this job I would fine-tuned a DistilBERT classifier on 38k historical tickets, kept a TF-IDF + logistic regression fallback for low-confidence cases, and exposed it behind an internal API.

Relevant skills: Natural Language Processing, Python Scikit-Learn, Machine Learning, Python. Happy to share more details on a call.

---

## 12. `ai_ml-prop-132`
**Job:** Automated Instagram profile with trainable chatgpt function

> Skills: Data Scraping, Python, Bot Development, Instagram, Chatbot Development, Instagram API, API

**Proposal:**

Hi there! I am very interested in your project and can start immediately.

For this job I would built an LLM-driven bot that extracts items, quantities and delivery slots into structured orders, with a human handover button and a menu-grounded prompt.

Relevant skills: Chatbot, ChatGPT, API Integration, Python. Happy to share more details on a call.

---

## 13. `ai_ml-prop-121`
**Job:** Room Floor Visualizer Website

> Skills: Website, Visualization, Python, Machine Learning, PyTorch, Computer Vision

**Proposal:**

Dear Sir/Madam, I am a passionate and hardworking professional with great experience.

For this job I would fine-tuned a DistilBERT classifier on 38k historical tickets, kept a TF-IDF + logistic regression fallback for low-confidence cases, and exposed it behind an internal API.

Relevant skills: Natural Language Processing, Python Scikit-Learn, Machine Learning, Python. Happy to share more details on a call.

---

## 14. `ai_ml-prop-019`
**Job:** Chrome extension using OpenAI API (proof of concept)

> Skills: API Development, ChatGPT, API, API Integration

**Proposal:**

Hello, I have read your job post and I am the perfect fit for this job.

For this job I would built a hybrid retrieval pipeline (keyword + embeddings) with clause-level chunking and citation of the source page in every answer.

Relevant skills: ChatGPT, Chatbot Development, Natural Language Processing, API Integration. Happy to share more details on a call.

---

## 15. `web_dev-prop-107`
**Job:** Wix Website Redesign I Optimisation

> Skills: Wix, Web Design

**Proposal:**

Hi - your post mentions wix. I solved a very similar problem for a US property-management startup: Onboarded 60 property companies in four months; page loads under 1.2 s at p95.

For this job I would built a Next.js dashboard with role-based access, tenant isolation in every query and server-side pagination.

Relevant skills: React, TypeScript, Next.js, PostgreSQL. Happy to share more details on a call.

---

## 16. `web_dev-prop-078`
**Job:** Duplicate a TRC-20 Smart Contract (Including Website) With Minor Changes

> Skills: Blockchain Development, Solidity, Blockchain, NFT & Cryptocurrency

**Proposal:**

Hi - your post mentions blockchain development. I solved a very similar problem for a US property-management startup: Onboarded 60 property companies in four months; page loads under 1.2 s at p95.

For this job I would built a Next.js dashboard with role-based access, tenant isolation in every query and server-side pagination.

Relevant skills: React, TypeScript, Next.js, PostgreSQL. Happy to share more details on a call.

---

## 17. `web_dev-prop-035`
**Job:** React JS / Backend / Web development / Wordpress / Webdesign

> Skills: Web Development, JavaScript, WordPress, React, Website Redesign, Node.js, MySQL, API Integration, API

**Proposal:**

Quick note on web development: in my appointment booking platform project for a chain of physiotherapy clinics, no-shows fell 38%; double bookings went to zero.

For this job I would built a booking web app with calendar slots per therapist, SMS/email reminders sent by a background job queue, and an admin view.

Relevant skills: React, Node.js, MongoDB, API Development. Happy to share more details on a call.

---

## 18. `web_dev-prop-027`
**Job:** Build new website for Digital Marketplace company

> Skills: Web Development, Web Design, WordPress, Graphic Design

**Proposal:**

Quick note on web development: in my multi-tenant saas admin dashboard project for a US property-management startup, onboarded 60 property companies in four months; page loads under 1.2 s at p95.

For this job I would built a Next.js dashboard with role-based access, tenant isolation in every query and server-side pagination.

Relevant skills: React, TypeScript, Next.js, PostgreSQL. Happy to share more details on a call.

---

## 19. `web_dev-prop-125`
**Job:** Senior WordPress Developer Needed

> Skills: Web Development, WordPress, PHP, CSS, Git, JavaScript, HTML, Docker

**Proposal:**

Quick note on web development: in my custom shopify storefront features project for a skincare brand in Canada, quiz takers converted at 6.1% versus 2.4% site average.

For this job I would built a quiz and bundle builder as theme app extensions calling the Storefront API.

Relevant skills: Shopify, JavaScript, API Integration, CSS. Happy to share more details on a call.

---

## 20. `web_dev-prop-010`
**Job:** Werd press one page document, no audio no video, jsut a document

> Skills: WordPress Development, Plugin Development, WordPress, PHP, Laravel, Angular, Shopify Theme, WordPress Plugin, Avada Theme Customization

**Proposal:**

Dear Sir/Madam, I am a passionate and hardworking professional with great experience.

For this job I would built a Next.js dashboard with role-based access, tenant isolation in every query and server-side pagination.

Relevant skills: React, TypeScript, Next.js, PostgreSQL. Happy to share more details on a call.

---

## 21. `web_dev-prop-110`
**Job:** Shopify store design

> Skills: Web Development, Shopify, Web Design, Design Enhancement, Shopify Templates, Adobe Photoshop

**Proposal:**

Hi there! I am very interested in your project and can start immediately.

For this job I would built a Next.js dashboard with role-based access, tenant isolation in every query and server-side pagination.

Relevant skills: React, TypeScript, Next.js, PostgreSQL. Happy to share more details on a call.

---

## 22. `web_dev-prop-126`
**Job:** Junior Engineer | Vue | Nuxt

> Skills: Vue.js, Nuxt.js

**Proposal:**

Hi there! I am very interested in your project and can start immediately.

For this job I would built a Next.js dashboard with role-based access, tenant isolation in every query and server-side pagination.

Relevant skills: React, TypeScript, Next.js, PostgreSQL. Happy to share more details on a call.

---

## 23. `web_dev-prop-043`
**Job:** Web AR developer with video game experience

> Skills: Game Development, Augmented Reality, JavaScript

**Proposal:**

Hello, I have read your job post and I am the perfect fit for this job.

For this job I would built a quiz and bundle builder as theme app extensions calling the Storefront API.

Relevant skills: Shopify, JavaScript, API Integration, CSS. Happy to share more details on a call.

---

## 24. `data_analysis-prop-141`
**Job:** Scrape website

> Skills: Data Scraping, Data Extraction

**Proposal:**

You need data scraping. Last year I built crm data cleaning and deduplication for a B2B software reseller, and removed 9,300 duplicates at 98% precision on a manual audit sample.

For this job I would built fuzzy-matching deduplication with a review queue for uncertain matches.

Relevant skills: Data Cleaning, Python, Data Extraction, Microsoft Excel. Happy to share more details on a call.

---

## 25. `data_analysis-prop-002`
**Job:** Generating Graphs from excel sheet with insights

> Skills: Tableau, Growth Analytics, Marketing Analytics, Sales, Analytics, Dashboard, Business Intelligence, Data Visualization

**Proposal:**

You need tableau. Last year I built operations kpi dashboard in tableau for a hospital network, and leadership reviews it daily; ER wait time breaches surfaced 2 days earlier on average.

For this job I would built a Tableau dashboard joining admissions, bed and ER data with drill-down by ward.

Relevant skills: Tableau, Dashboard, SQL, Data Visualization. Happy to share more details on a call.

---

## 26. `data_analysis-prop-115`
**Job:** Help with Amazon, Walmart, and etsy Listing creation and management-must have experience

> Skills: Amazon, Etsy Listing, Product Listings, Competitive Analysis, Marketing, Inventory Management, Customer Service, Analytics, Amazon Seller Central

**Proposal:**

You need amazon. Last year I built product usage funnel analysis for a mobile fitness app, and day-1 activation rose from 30% to 41% after the onboarding change.

For this job I would built event-level funnels and cohorts, found the drop at the permissions screen, and analysed the fix experiment.

Relevant skills: Analytics, SQL, Data Visualization, A/B Testing. Happy to share more details on a call.

---

## 27. `data_analysis-prop-015`
**Job:** Power BI Data Visualization Developer

> Skills: Microsoft Power BI Data Visualization, Data Visualization, Data Modeling, Transact-SQL

**Proposal:**

Quick note on microsoft power bi data visualization: in my sales performance dashboard project for a FMCG distributor in Karachi, monthly reporting time went from 3 days to 0; 45 managers use it weekly.

For this job I would modelled sales, targets and distributor data into a star schema and built a Power BI dashboard refreshed daily.

Relevant skills: Microsoft Power BI, Dashboard, SQL, Data Modeling. Happy to share more details on a call.

---

## 28. `data_analysis-prop-014`
**Job:** Google Analytics 4 Expert

> Skills: Google Analytics, Google Tag Manager, Analytics

**Proposal:**

Hi - your post mentions google analytics. I solved a very similar problem for a US DTC supplements brand: Reallocated 22% of budget from paid social to search; blended CAC down 17%.

For this job I would built GA4 export pipelines into BigQuery, transformation models for sessions and orders, and a multi-touch attribution report.

Relevant skills: Marketing Analytics, Google Analytics, SQL, BigQuery. Happy to share more details on a call.

---

## 29. `data_analysis-prop-008`
**Job:** Experienced Lead Scraper, Email Lead List Building

> Skills: Data Cleansing, Life Science, Data Scraping, Data Mining, List Building, Prospect List, Lead Generation, Data Entry, Market Research

**Proposal:**

Dear Sir/Madam, I am a passionate and hardworking professional with great experience.

For this job I would ran association-rule mining on 2M receipts and recommended cross-promotions and shelf placements.

Relevant skills: Data Analysis, Python, Statistics, Data Mining. Happy to share more details on a call.

---

## 30. `data_analysis-prop-064`
**Job:** Data Analyst for New Beginners

> Skills: Data Analysis, Statistical Analysis, Data Visualization, Microsoft Excel, Data Entry

**Proposal:**

Hello, I have read your job post and I am the perfect fit for this job.

For this job I would ran survival analysis on tenure by shift, manager and pay band, and presented the drivers to leadership.

Relevant skills: Data Analysis, Statistics, Python, Data Visualization. Happy to share more details on a call.

---
