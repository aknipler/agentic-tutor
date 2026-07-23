import os
from typing import Dict, Optional, List
import streamlit as st
from openai import OpenAI
import base64

def initialize_openai_client() -> OpenAI:
    """Initialize the OpenAI client with API key from environment variable"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        st.warning("OpenAI API key not found. Please set the OPENAI_API_KEY environment variable.")
        return None
    
    return OpenAI(api_key=api_key)

def _is_reasoning_model(model: str) -> bool:
    """gpt-5 and o-series models accept `reasoning_effort`; anything else (e.g.
    gpt-4o-mini) rejects it outright as an unsupported parameter."""
    return model.startswith(("gpt-5", "o1", "o3", "o4"))

def assess_answer(
    question: str,
    answer: str,
    expected_answer: str,
    image_data_list: Optional[List[bytes]] = None,
    model: str = "gpt-4o-mini",
    success_criteria: str = "",
    max_completion_tokens: int = 1000,
    reasoning_effort: Optional[str] = "low"
) -> Dict:
    """
    Assess a student's answer using OpenAI API

    Args:
        question: The question text
        answer: The student's answer text
        expected_answer: The expected/model answer text
        image_data_list: Optional list of image bytes for images the student uploaded
        model: The OpenAI model to use for assessment
        success_criteria: The success criteria for the question (optional)
        max_completion_tokens: Cap on the model's total output (visible feedback +
            hidden reasoning, for reasoning models). Measured against gpt-5-nano:
            a normal assessment used ~170 tokens at reasoning_effort="low", so
            1000 leaves real margin without being reckless on cost.
        reasoning_effort: Passed straight through to reasoning models
            (gpt-5-nano, o-series); ignored by non-reasoning models like
            gpt-4o-mini, which don't accept the parameter at all.
        
    Returns:
        Dictionary containing assessment results:
        {
            "competency_level": int,  # Competency level (0, 1, or 2)
            "feedback": str,          # Feedback for the student
            "status": str,            # Status (completed, in_progress)
            "response_text": str,     # Raw response text from OpenAI
            "input_image_data": Optional[List[bytes]] # List of input image bytes
        }
    """
    print(f"Assessing answer: {expected_answer}")

    if st.session_state.get('debug_mode', False):
        st.write(f"Debug: Assessing answer for question: {question}")
        st.write(f"Debug: Student answer: {answer}")
        st.write(f"Debug: Expected answer: {expected_answer}")
        st.write(f"Debug: Success criteria: {success_criteria}")
        if image_data_list:
            st.write(f"Debug: Number of images provided: {len(image_data_list)}")
        else:
            st.write("Debug: No images provided.")
        st.write(f"Debug: Using model: {model}")

    # Initialize OpenAI client
    client = initialize_openai_client()
    if not client:
        return {
            "competency_level": 0,
            "feedback": "Unable to assess answer. Please try again later.",
            "status": "in_progress",
            "response_text": "",
            "input_image_data": image_data_list
        }
    
    # Define the core instructions for the assessor role
    core_instructions = f"""As an education assessor, evaluate the student's answer provided in the user message based on the question and expected answer provided in the system message context.

Provide a competency level (0, 1, or 2) and constructive feedback. Use the following criteria:
- Level 0: No attempt
- Level 1: Answer with some understanding
- Level 2: Correct answer

**Format the feedback using markdown for clarity (e.g., use bullet points or bold text where appropriate).**

Format your response strictly as:
Competency Level: [level]
Feedback: [feedback]

Be generous with your competency level rating. When it is unclear if the student has partial understanding or full understanding, give them the benefit of the doubt and give them a full competency level.

Formatting: Wrap inline math in $...$ and block equations in $$...$$ (and explicitly not \(...\)/\[...\]).

"""

    # Add success criteria to the context if provided
    success_criteria_text = f"\n\nSuccess Criteria: {success_criteria}" if success_criteria else ""

    # Build user submission content (Student Answer + Images)
    user_submission_content = [
        {"type": "input_text", "text": f"Student Answer: {answer}"}
    ]

    # Add images to user submission content if provided
    if image_data_list:
        for image_data in image_data_list:
            try:
                base64_image = base64.b64encode(image_data).decode('utf-8')
                data_uri = f"data:image/jpeg;base64,{base64_image}" # Assuming jpeg
                user_submission_content.append({
                    "type": "input_image", 
                    "image_url": {
                        "url": data_uri,
                        "detail": "high"
                    }
                })
            except Exception as e:
                st.warning(f"Could not process one of the images: {e}")

    # Default values before API call
    competency_level = 0
    feedback = "Error during assessment process."
    status = "in_progress"
    response_text = ""

    try:
        # Prepare messages for the chat completions endpoint
        messages = []

        # System message combining instructions and context
        system_prompt = f"""{core_instructions}

Context for Assessment:
Question: {question}

Expected Answer: {expected_answer}{success_criteria_text}"""
        


        messages.append({"role": "system", "content": system_prompt})

        # User message combining student answer and images
        user_content = [{"type": "text", "text": f"Student Answer: {answer}"}]
        if image_data_list:
            for image_data in image_data_list:
                try:
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    data_uri = f"data:image/jpeg;base64,{base64_image}" # Assuming jpeg
                    user_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": data_uri,
                            "detail": "high" # or "low" or "auto"
                        }
                    })
                except Exception as e:
                    st.warning(f"Could not process one of the images for API call: {e}")
        
        messages.append({"role": "user", "content": user_content})

        # Call OpenAI Chat Completions API. `max_tokens` is rejected outright
        # by reasoning models (gpt-5, o-series) - `max_completion_tokens` is
        # the current parameter and works for both reasoning and non-reasoning
        # models, so it's used unconditionally.
        completion_kwargs = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
        }
        if reasoning_effort and _is_reasoning_model(model):
            completion_kwargs["reasoning_effort"] = reasoning_effort

        response = client.chat.completions.create(**completion_kwargs)

        # Extract content from the response
        response_text = response.choices[0].message.content if response.choices else ""

        # Reset defaults for parsing
        competency_level = 0
        feedback = "No feedback provided."

        try:
            # Find the position of "Feedback:" case-insensitively
            feedback_marker = "feedback:"
            feedback_start_index = response_text.lower().index(feedback_marker)
            
            # Extract everything after the marker
            raw_feedback = response_text[feedback_start_index + len(feedback_marker):]
            
            # Strip leading/trailing whitespace/newlines
            feedback = raw_feedback.strip()
            
            # If feedback is empty after stripping, revert to default
            if not feedback:
                feedback = "No feedback provided."
                
        except ValueError:
            # "Feedback:" marker not found, keep default feedback
            st.warning("Could not find 'Feedback:' marker in the response.")
            pass # Keep default feedback = "No feedback provided."

        # Parse competency level
        for line in response_text.split('\n'):
            if line.lower().startswith("competency level:"):
                try:
                    # Extract number from the competency level line
                    level_text = line.split(':', 1)[1].strip()
                    competency_level = int(level_text)
                    # Ensure competency level is between 0 and 2
                    competency_level = max(0, min(2, competency_level))
                except ValueError:
                    st.warning(f"Could not parse competency level from line: {line}")
                    pass

        # Determine status based on competency level
        status = "completed" if competency_level >= 1 else "in_progress"

        return {
            "competency_level": competency_level,
            "feedback": feedback,
            "status": status,
            "response_text": response_text,
            "input_image_data": image_data_list
        }

    except Exception as e:
        st.error(f"Error assessing answer: {str(e)}")
        return {
            "competency_level": 0,
            "feedback": f"Error assessing answer: {str(e)}",
            "status": "in_progress",
            "response_text": "",
            "input_image_data": image_data_list
        } 