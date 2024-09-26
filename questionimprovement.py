import openai
from openai_config import setup_openai

model_engine = setup_openai()

#Mejora la pregunta realizada, con ChatGPT
def improveQuestionchatGPT(question):
    # manejar el prompt para que devuelva un json con parámetros faltantes.
    #prompt = "Give me only one alternative question for this one in the scope of restaurant booking: " + question

    messages = [
        {
            "role": "user",
            "content": "Provided the question " + question + " in the scope of restaurant booking, give me only one alternative question"
        }
    ]

    # Crear la solicitud de ChatCompletion
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",  #Puedes usar "gpt-4" si tienes acceso
        messages=messages,
        temperature=0.8,
        max_tokens=64,
        top_p=1,
        frequency_penalty=0.5,
        presence_penalty=0
    )

    # Extraer la respuesta generada por el modelo
    generated_text = response.choices[0].message.content
    print(generated_text)

    final_response = response.choices[0].message.content

    if not final_response:
        final_response = question

    return final_response