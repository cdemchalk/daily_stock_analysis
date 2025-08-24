#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug  2 20:33:01 2025

@author: cdemchalk
"""

from openai import OpenAI
import os

def summarize_insights(ticker, ta, fundamentals, news):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = f"""
Summarize for {ticker} in a concise investor-ready take (500-800 words) with near-term risk/opportunity and obvious catalysts or caution flags.
 Structure the response in clear paragraphs, separating key sections: Technicals, Fundamentals, Opportunities, Risks, and Catalysts.
 Each section should start with a new paragraph and a bolded header (e.g., **Technicals**).
 Use specific details from the provided data and avoid generic financial jargon unless directly supported.

**Technicals**: {ta}

**Fundamentals**: {fundamentals}

**Full News Articles and Social Snippets (top items included)**: {news}
"""
    resp = client.chat.completions.create(
        model="gpt-5",
        messages=[{"role":"user","content":prompt}]
    )
    return resp.choices[0].message.content.strip()