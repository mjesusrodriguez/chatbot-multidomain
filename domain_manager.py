import openai
from openai_config import setup_openai

model_engine = setup_openai()

def domain_manager_gpt(input):
    messages = [
        {
            "role": "user",
            "content": "You are a domain classificator in a dialogue system, classify the following input:" + input + " into one of the four domains: \"restaurants\", \"hotels\", \"attractions\", or \"out-of-domain\" and return just one word with the domain."
        }
    ]

    # Crear la solicitud de ChatCompletion
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",  # Puedes usar "gpt-4" si tienes acceso
        messages=messages,
        temperature=0,
        max_tokens=64,
        top_p=1,
        frequency_penalty=0.5,
        presence_penalty=0
    )

    # Extraer la respuesta generada por el modelo
    generated_text = response.choices[0].message.content
    print(generated_text)

    final_response = response.choices[0].message.content

    return final_response