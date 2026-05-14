from .rag import retrieve_schema

def build_prompt(user_query):
    relevant = retrieve_schema(user_query)

    return f"""
You are a strict SQL generator.

Relevant schema:
{relevant}

Full schema:
v_course_info(course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom)

Column details:
- day_of_week: string containing Korean days (e.g., '월', '목'). Do NOT use integers.
- section: string representing the class section (e.g., '01', '02'). ALWAYS use string literals with single quotes (e.g., section = '01', NOT section = 1).
- category: Course category. Use EXACTLY the name requested by the user (e.g., '전공', '교양', '전공(기초)', '전공(핵심)', '교양(균형)'). Example: if user asks for '전공(핵심)', use category LIKE '%전공(핵심)%'.
- start_time: Course start time. For '오전' (morning), use start_time < '12:00'. For '오후' (afternoon), use start_time >= '12:00'.
- class_mode: Do NOT use this column unless the user explicitly asks for online/offline/real-time classes.



Rules:
- ONLY SELECT
- USE ONLY the tables and columns listed in the schema above.
- DO NOT invent or guess table names (e.g., never use 'courses', use 'v_course_info' instead).
- For string comparisons (like dept_name, subject_name), ALWAYS use LIKE '%word%' instead of exact match '='.
- If unclear → UNKNOWN

User: {user_query}
SQL:
"""
