import os
from typing import Dict, Optional
import streamlit as st
from openai import OpenAI

def initialize_openai_client() -> OpenAI:
    """Initialize the OpenAI client with API key from environment variable"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        st.warning("OpenAI API key not found. Please set the OPENAI_API_KEY environment variable.")
        return None
    
    return OpenAI(api_key=api_key)

def assess_answer(
    question: str, 
    answer: str, 
    image_url: Optional[str] = None,
    model: str = "gpt-4o-mini"
) -> Dict:
    """
    Assess a student's answer using OpenAI API
    
    Args:
        question: The question text
        answer: The student's answer text
        image_url: Optional URL to an image the student uploaded
        model: The OpenAI model to use for assessment
        
    Returns:
        Dictionary containing assessment results:
        {
            "score": float,  # Score between 0 and 1
            "feedback": str,  # Feedback for the student
            "status": str,    # Status (completed, in_progress)
        }
    """
    # Initialize OpenAI client
    client = initialize_openai_client()
    if not client:
        return {
            "score": 0,
            "feedback": "Unable to assess answer. Please try again later.",
            "status": "in_progress"
        }
    
    # Build content list for the API request
    content = [
        {"type": "input_text", "text": f"As an education assessor, evaluate this student's answer to the following question:\n\nQuestion: {question}\n\nStudent Answer: {answer}\n\nProvide a score from 0 to 100 and constructive feedback. Format your response as:\nScore: [score]\nFeedback: [feedback]"}
    ]
    
    # Add image if provided
    if image_url:
        content.append({
            "type": "input_image",
            "image_url": image_url,
            "detail": "high"
        })
    
    try:
        # Call OpenAI API
        response = client.responses.create(
            model=model,
            input=[{
                "role": "user",
                "content": content,
            }],
        )
        
        # Extract score and feedback from response
        response_text = response.output_text
        
        # Simple parsing of response text
        score = 0
        feedback = "No feedback provided."
        
        for line in response_text.split('\n'):
            if line.lower().startswith("score:"):
                try:
                    # Extract number from the score line
                    score_text = line.split(':', 1)[1].strip()
                    score = float(score_text.split('/')[0].strip()) if '/' in score_text else float(score_text)
                    # Normalize to 0-1 scale if score is out of 100
                    if score > 1:
                        score /= 100
                except:
                    pass
            elif line.lower().startswith("feedback:"):
                feedback = line.split(':', 1)[1].strip()
        
        # Determine status based on score
        status = "completed" if score >= 0.7 else "in_progress"
        
        return {
            "score": score,
            "feedback": feedback,
            "status": status
        }
        
    except Exception as e:
        st.error(f"Error assessing answer: {str(e)}")
        return {
            "score": 0,
            "feedback": f"Error assessing answer: {str(e)}",
            "status": "in_progress"
        } 