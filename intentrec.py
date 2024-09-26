#hace el reconocimiento de intent con ChatGPT
import json
import openai

from mongo_config import get_database
from openai_config import setup_openai

model_engine = setup_openai()

def getIntents():
    # obtener la base de datos de intents
    db_intents = get_database("intents")
    intents_collection = db_intents.restaurant

    # Step 3: Query the collection to get all the intents
    intents_cursor = intents_collection.find({}, {'intent': 1})  # Fetch all documents, but only the 'intent' field

    # Step 4: Extract intent names and save them into an array
    intents_list = [doc['intent'] for doc in intents_cursor if 'intent' in doc]

    print("LOS INTENTS SON: ", intents_list)
    return intents_list

def intentRecWithChatGPT2(input):
    intent_array = getIntents()
    # Convertir el vector a una cadena de caracteres con comas
    intents = ','.join(map(str, intent_array))


    messages = [
        {
            "role": "user",
            "content": "You are a chatbot in the restaurant domain, and your task is to determine the intent behind a user's input or query. Below is a list of intents related to the restaurant domain: "+ intents +". Given the input '"+input+"', determine the intent of the user based on the provided intents, return a JSON with only one. Consider that users often want to make reservations when specifying a type of restaurant."
        }
    ]

    # Crear la solicitud de ChatCompletion
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",  # Puedes usar "gpt-4" si tienes acceso
        messages=messages,
        temperature=0.3,
        max_tokens=64,
        top_p=1,
        frequency_penalty=0.5,
        presence_penalty=0
    )

    # Extraer la respuesta generada por el modelo
    generated_text = response.choices[0].message.content
    print(generated_text)

    # Procesar el JSON para obtener solo el "intent"
    try:
        data = json.loads(generated_text)  # Asegúrate de analizar el texto generado como JSON
        intent = data.get("intent")  # Obtener el valor de "intent"
    except json.JSONDecodeError:
        print("Error al decodificar JSON")
        intent = None

    return intent

def intentRecWithChatGPT(input):
    #Cojo los intents que estén en la BBDD
    intents = getIntents()

    #prompt="for the following input \""+input+"\" give me a JSON with only an intent of the user between those: BookRestaurant, PlayMusic, AddToPlayList, RateBook, SearchScreeningEvent, GetWeather, SearchCreativeWork"
    prompt = "You are a chatbot in the restaurant domain, and your task is to determine the intent behind a user's input or query. Below is a list of intents related to the restaurant domain: BookRestaurant, RestaurantInformation, FindRestaurant, OrderFood. Given the input '"+input+"', determine the intent of the user based on the provided intents, return a JSON with only one. Consider that users often want to make reservations when specifying a type of restaurant."
    completion = openai.Completion.create(
        engine=model_engine,
        prompt=prompt,
        temperature=0.3,
        max_tokens=64,
        top_p=1,
        frequency_penalty=0.5,
        presence_penalty=0)
    response = completion.choices[0].text
    print(response)

    #Proceso JSON
    data = json.loads(response)
    intent = data["intent"]
    return intent