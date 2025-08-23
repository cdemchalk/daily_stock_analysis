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
Summarize for {ticker}:

Technical: {ta}
Fundamentals: {fundamentals}
Full News Articles and Social Snippets (top items included): {news}

Give a concise investor-ready take (500-1000 words) with near-term risk/opportunity,
and mention any obvious catalysts or caution flags. Seperate key sections as paragraphs 
for easy reading and also provide a short summary of each article that you reviewed. 
"""
    resp = client.chat.completions.create(
        model="gpt-5",
        messages=[{"role":"user","content":prompt}]
    )
    return resp.choices[0].message.content.strip()