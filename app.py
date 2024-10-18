from bson import ObjectId
from flask import Flask, render_template, request, jsonify
import json
import random
import requests
import re

from disc_parameter import get_top_parameters_combined, update_frequencies_for_requested_slots, \
    detect_and_update_other_slots
from domain_manager import domain_manager_gpt
from intentrec import intentRecWithChatGPT
from mongo_config import MongoDB
from openai_config import setup_openai
from opendomain import opendomainconversation
from questionimprovement import improveQuestionchatGPT, createQuestionGPT
from questionretrieval import questionsRetrieval
from slotfilling import extractSlots, slotFillingGPT
from tagfilter import tagFilter, getAditionalQuestions

app = Flask(__name__)

# Obtener la base de datos
db = MongoDB()
# Obtener la colección de servicios de restaurantes
#restaurant_sv = db.restaurant

model_engine = setup_openai()

#Variable global para guardar el servicio
service_id = ""
#variable global para guardar el intent
intent = ""
#variable para guardar la historia del diálogo
dialogue_history = {}

#Devolver los servicios filtrados según los tags que contengan
def filterServicesByTag(intentServices, userTags, domain):
    #tagServices = []
    services = {}

    collection = db.get_collection(domain, 'services')

    for service_id in intentServices:
        #Busco el servicio por id
        document = collection.find_one({"_id": ObjectId(service_id)})

        #Encuentro el servicio (debería siempre darlo ya que lo hemos guardado previamente)
        if document:
            # Itero el JSON y saco los intents que tiene definido el servicio
            for tag_document in document.get('tags', []):
                tags = tag_document.get("name", "")

                #divido en tokens
                tagList = {substring.strip() for substring in tags.split(',')}

                #Por cada etiqueta del servicio que esté en las etiquetas del usuario
                for tag in userTags:
                    if tag.lower() in tagList:
                        services[service_id] = services.get(service_id, 0) + 1

            #No hemos registrado ninguna etiqueta para ese servicio así que 0
            if service_id not in services:
                services[service_id] = 0

    # Ordena el diccionario por sus valores en orden ascendente
    sorted_services = dict(sorted(services.items(), key=lambda item: item[1]))
    return sorted_services

def detect_positive_answers(response_dict):
    positive_keywords = ["yes", "yeah", "yep", "sure", "absolutely", "definitely", "of course"]
    positive_tags = []

    for tag, answer in response_dict.items():
        response_lower = answer.lower()
        if any(word in response_lower for word in positive_keywords):
            positive_tags.append(tag)

    return positive_tags

# Lista de palabras clave de despedida
goodbye_keywords = ['goodbye', 'bye', 'see you', 'later', 'farewell', 'take care', 'thanks', 'thank you', 'talk to you later', 'bye bye']

def check_for_goodbye(user_input):
    # Normaliza el input del usuario a minúsculas y compara con las palabras clave
    for keyword in goodbye_keywords:
        if re.search(rf'\b{keyword}\b', user_input.lower()):
            return True
    return False

# Lista de frases comunes que indican un posible dominio abierto
open_domain_phrases = [
    r'what do you think',  # Detectar preguntas del tipo "What do you think..."
    r'tell me about',      # Preguntas más generales del tipo "Tell me about..."
    r'can you share',      # Preguntas como "Can you share..."
    r'what is your opinion',  # Preguntas como "What is your opinion..."
    r'explain to me',      # Expresiones como "Explain to me..."
    # Puedes añadir más patrones si es necesario
]

# Función para detectar dominio abierto mediante patrones
def detect_open_domain(user_input):
    for phrase in open_domain_phrases:
        if re.search(phrase, user_input.lower()):
            return True
    return False

@app.route('/')
def index():
    return render_template('chat.html')

# PRIMERA INTERACCIÓN CON EL USUARIO
@app.route('/intent', methods=['POST'])
def intentrec():
    print("entro en intent")
    questions = {}

    # Obtener datos del cuerpo de la solicitud POST
    data = request.get_json()  # Utiliza get_json() para obtener datos JSON
    # Verificar si se recibieron datos
    if not data:
        return jsonify({"error": "No data received"}), 400

    # Extraer los datos recibidos
    userInput = data.get('userinput')
    print(userInput)

    userAnswers = data.get('useranswers')
    print("USER ANSWERS: ", userAnswers)
    if userAnswers is None:
        userAnswers = []

    # Comprobar si el usuario se ha despedido
    if check_for_goodbye(userInput):
        # Actualizar el historial en 'userAnswers'
        userAnswers.append({"user": userInput, "chatbot": "Thank you for chatting! Goodbye!"})
        return jsonify({"chatbot_answer": "Thank you for chatting! Goodbye!", "end_conversation": True, "useranswers": userAnswers})

    # Predicción de dominio
    domain = domain_manager_gpt(userInput)
    print("DOMAIN: ", domain)

    # Detectar si el input pertenece a dominio abierto con patrones conocidos
    if detect_open_domain(userInput):
        print("Detectado como dominio abierto por patrón")
        domain = 'out-of-domain'

    # Si el dominio es out-of-domain llamo al generador de diálogo abierto, con la historia del diálogo
    if domain.lower() == "out-of-domain":
        print("ENTRO EN OUT-OF-DOMAIN")
        chatbot_answer = opendomainconversation(userInput, userAnswers)
        # Agregar la interacción actual al historial de 'userAnswers'
        userAnswers.append({"user": userInput, "chatbot": chatbot_answer})
        return jsonify({'chatbot_answer': chatbot_answer, 'dom': domain.lower(), 'useranswers': userAnswers}), 200

    # Obtener los dos parámetros más frecuentes
    top_slots_list = get_top_parameters_combined(domain)
    print("Dos parámetros más frecuentes:", top_slots_list)

    # Inicializar el diccionario filledParams con los nombres de los slots rescatados
    filledParams = {slot['parameter']: '' for slot in top_slots_list}
    print("FilledSlots inicial:", filledParams)

    # Reconocimiento de intent - Servicio intentrec
    user_intent = intentRecWithChatGPT(userInput, domain)
    intent = user_intent.lower()
    print(intent)

    # Ahora puedes usar top_slots_list sin problemas para extraer los nombres de los slots
    print("Contenido de top_slots:", top_slots_list)  # Ya convertido en lista previamente

    reqSlots = [slot['parameter'] for slot in top_slots_list]
    print("Slots requeridos:", reqSlots)

    # Slot filling con GPT
    slots = slotFillingGPT(userInput, reqSlots)
    print("Slots generados:", slots)

    # Verifica si slots es una cadena y convierte en lista de diccionarios
    if isinstance(slots, str):
        try:
            slots_list = json.loads(slots)  # Convertir de cadena JSON a lista de diccionarios o diccionario
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format for 'slots': {e}")
    else:
        slots_list = slots

    # Asegurarse de que 'slots_list' sea un diccionario o lista de diccionarios
    if isinstance(slots_list, dict):
        slots_list = [slots_list]  # Convertir el diccionario a una lista con un solo elemento
    elif not isinstance(slots_list, list):
        raise TypeError(f"Expected 'slots' to be of type 'list' or 'dict', got {type(slots_list)}")

    # Actualizamos los slots rellenados en filledParams
    try:
        for slots_dict in slots_list:
            if isinstance(slots_dict, dict):
                for param, value in slots_dict.items():
                    # Si el valor no es "Null", llenamos el slot en filledParams
                    if value != "Null":
                        filledParams[param] = value
    except Exception as e:
        print(f"An error occurred: {e}")

    # Generamos preguntas para los slots no rellenados (aquellos con valor "Null")
    null_params = [param for slots_dict in slots_list for param, value in slots_dict.items() if value == "Null"]

    # Crear una pregunta para cada slot no rellenado (valor "Null") usando GPT
    for param in null_params:
        # Usar GPT para generar una pregunta personalizada para cada parámetro no rellenado
        questions[param] = createQuestionGPT(param, domain)

    # Ahora usamos slots_list en lugar de slots
    update_frequencies_for_requested_slots(slots_list, reqSlots, domain)

    # Detectar y actualizar otros slots que el usuario haya mencionado pero no sean los top solicitados
    detect_and_update_other_slots(userInput, top_slots_list, domain)

    return jsonify({'questions': questions, 'filled': filledParams, 'intent': intent, 'userinput': userInput, 'dom': domain, 'reqslots': reqSlots}), 202

#SEGUNDA INTERACCIÓN CON EL USUARIO
@app.route('/chat', methods=['GET', 'POST'])
def chat():
    emptyParams = {}
    filledParams = {}

    # Get the JSON data from the request
    data_from_client = request.get_json()

    # Debug: Print the received data
    print("Received data from client:", data_from_client)

    # Check if data is None
    if data_from_client is None:
        print("No data received or incorrect Content-Type header")
        return jsonify({"error": "No data received"}), 400

    intent = data_from_client["intent"]
    domain = data_from_client["domain"]
    userInput = data_from_client["userinput"]
    userAnswers = data_from_client.get('useranswers', [])

    reqSlots = data_from_client["reqslots"]

    if check_for_goodbye(userInput):
        return jsonify({"chatbot_answer": "Thank you for chatting! Goodbye!", "end_conversation": True})

    # Crear una lista para los parámetros dinámicos
    dynamic_params = reqSlots  # Todos los slots dinámicos

    #Selecciono un servicio
    services = tagFilter(userInput, intent, data_from_client, domain)

    # Voy a coger los parámetros discriminatorios de los servicios si son más de uno.
    if len(services) > 1:
        aditional_questions, filledParams = getAditionalQuestions(services, userInput, intent, data_from_client, domain)
        return jsonify(
            {'questions': aditional_questions, 'filled': filledParams, 'intent': intent, 'userinput': userInput, 'services': [str(service) for service in services], 'useranswers': userAnswers, 'dom': domain, 'reqslots': reqSlots}), 202

    else:
        # Selecciono el que se ha devuelto
        service_id = services[0]

        # Consulto en los servicios que tengo que campos se han rellenado ya y cuales faltan y devuelvo las preguntas.
        slots = extractSlots(intent, service_id, domain)
        slotFillingResponse = slotFillingGPT(userInput, slots, userAnswers)

        # Verificar el tipo de respuesta
        print(f"Respuesta de slotFillingGPT: {slotFillingResponse}")

        # Convertir la respuesta en una lista de diccionarios
        sf_data = json.loads(slotFillingResponse)

        # Verifica si sf_data es una lista o un diccionario
        if isinstance(sf_data, list):
            # Iterar sobre cada elemento de la lista (donde cada elemento es un diccionario)
            for item in sf_data:
                if isinstance(item, dict):
                    for key, value in item.items():
                        if value == "Null":
                            emptyParams[key] = value
                        else:
                            filledParams[key] = value
        elif isinstance(sf_data, dict):
            # Si sf_data es un diccionario, itera sobre él directamente
            for key, value in sf_data.items():
                if value == "Null":
                    emptyParams[key] = value
                else:
                    filledParams[key] = value
        else:
            raise TypeError(f"Expected list or dict, got {type(sf_data)}")

        # Mostrar los resultados de los parámetros vacíos y llenos
        print(f"Parámetros vacíos (emptyParams): {emptyParams}")
        print(f"Parámetros llenos (filledParams): {filledParams}")

        # Eliminar los slots que ya han sido llenados desde dynamic_params
        for param in dynamic_params:
            if param in emptyParams:
                emptyParams.pop(param)

        print("EMPTY PARAMS")
        print(emptyParams)

        # Evitar posibles errores, rellenar filledParams con los slots iniciales desde dynamic_params
        for param in dynamic_params:
            filledParams[param] = data_from_client["filledSlots"].get(param, "")

        print("FILLED PARAMS")
        print(filledParams)

        # hago una llamada a la función que dado un intent y un id me da las preguntas.
        intent_info = questionsRetrieval(service_id, intent, domain)

        # Cuento la cantidad de parametros que hay en el json
        intent_info_json = intent_info[0].json
        slots = intent_info_json["intent"]["slots"]
        print("SLOTS", slots)

        json_slots = json.dumps(emptyParams)
        parsed_items = json.loads(json_slots)
        print("PARSED")
        print(parsed_items)

        # Guardo las preguntas de los parámetros que hacen falta.
        questions = {}

        for empty in parsed_items:
            if parsed_items[empty] == 'Null':  # Solo procesar si el slot aún no ha sido llenado
                # Buscar en 'slots' el valor de la clave correspondiente a 'empty'
                if empty in slots:
                    # Eliminar comillas dobles si existen
                    question = slots[empty].replace('"', '')

                    # Mejorar la pregunta con el método
                    improved_question = improveQuestionchatGPT(question)
                    questions[empty] = improved_question
                else:
                    print(f"Error: {empty} no se encontró en los slots.")

        # return questions
        print("QUESTIONS")
        print(questions)
        return jsonify(
            {'questions': questions, 'filled': filledParams, 'service_id': str(service_id), 'intent': intent, 'useranswers': userAnswers, 'reqslots': reqSlots}), 202

#TERCERA INTERACCIÓN CON EL USUARIO.
@app.route('/slotfilling', methods=['GET', 'POST'])
def slotfilling():
    #cojo del cliente los datos
    data_from_client = request.get_json()
    print(data_from_client)

    emptyParams = {}
    filledParams = {}
    intent = data_from_client["intent"]
    userInput = data_from_client["userinput"]
    userAnswers = data_from_client["useranswers"]
    domain = data_from_client["domain"]

    # Obtener los slots dinámicos de reqslots
    reqSlots = data_from_client.get("reqslots", {})

    # Crear una lista para los parámetros dinámicos
    dynamic_params = reqSlots  # Todos los slots dinámicos

    if check_for_goodbye(userInput):
        return jsonify({"chatbot_answer": "Thank you for chatting! Goodbye!", "end_conversation": True})

    #cojo los datos de filledParams
    filledParams = data_from_client["filledSlots"]
    #Evalúo si para cada tag la respuesta es positiva o negativa.
    positive_tags = detect_positive_answers(filledParams)
    print("POSITIVE TAGS")
    print(positive_tags)
    #Filtro por esos tags con los servicios recogidos del cliente
    services = data_from_client["services"]
    services = [ObjectId(service) for service in services]
    print("SERVICES")
    print(services)
    selected_services = []
    selected_services = filterServicesByTag(services, positive_tags, domain)
    print("SELECTED SERVICES BY NEW TAGS")
    print(selected_services)

    # Get the maximum value in the dictionary
    max_value = max(selected_services.values())

    # Get all keys (service_ids) with the maximum value
    max_value_services = [service_id for service_id, value in selected_services.items() if value == max_value]

    # Now you can check the length of max_value_services
    if len(max_value_services) > 1:
        # There are multiple services with the maximum value
        # You can select one of them randomly or based on some other criteria
        service_id = random.choice(max_value_services)
    else:
        # There is only one service with the maximum value
        service_id = max_value_services[0]

    print("SERVICE SELECTED")
    print(service_id)

    #CONTINUACIÓN DEL FLUJO NORMAL
    #extraigo los slots
    slots = extractSlots(intent, service_id, domain)

    # Le paso los slots a la tarea de SF, como es una tercera interacción, voy a pasarle el histórico del diálogo, para que rellene también
    # según ha contestado en las preguntas intermedias.
    slotFillingResponse = slotFillingGPT(userInput, slots, userAnswers)
    print("Los slots rellenos con el cambio son:" + slotFillingResponse)

    # Convert the string to a dictionary
    sf_data = json.loads(slotFillingResponse)

    # Verificar si sf_data es una lista o un diccionario
    if isinstance(sf_data, list):
        # Si es una lista, iterar por la lista de diccionarios
        for item in sf_data:
            for key, value in item.items():
                if value == "Null":
                    emptyParams[key] = value
                else:
                    filledParams[key] = value
    elif isinstance(sf_data, dict):
        # Si es un diccionario, iterar directamente
        for key, value in sf_data.items():
            if value == "Null":
                emptyParams[key] = value
            else:
                filledParams[key] = value

    # Eliminar los slots que ya han sido llenados desde dynamic_params
    for param in dynamic_params:
        if param in emptyParams:
            emptyParams.pop(param)

    print("EMPTY PARAMS")
    print(emptyParams)

    # Evitar posibles errores, rellenar filledParams con los slots iniciales desde dynamic_params
    for param in dynamic_params:
        # Como reqSlots es una lista, verificamos si param está en esa lista
        if param in reqSlots:
            filledParams[param] = ""  # Puedes ajustar el valor predeterminado si es necesario
        else:
            filledParams[param] = "Null"  # O el valor por defecto si no está presente

    print("FILLED PARAMS")
    print(filledParams)

    # hago una llamada a la función que dado un intent y un id me da las preguntas.
    intent_info = questionsRetrieval(service_id, intent, domain)

    # Cuento la cantidad de parametros que hay en el json
    intent_info_json = intent_info[0].json
    slots = intent_info_json["intent"]["slots"]

    json_slots = json.dumps(emptyParams)
    parsed_items = json.loads(json_slots)
    print("PARSED")
    print(parsed_items)

    # Guardo las preguntas de los parámetros que hacen falta.
    questions = {}
    for empty in parsed_items:
        improved_question = improveQuestionchatGPT(slots[empty])
        questions[empty] = improved_question

    # return questions
    print("QUESTIONS")
    print(questions)
    return jsonify(
        {'questions': questions, 'filled': filledParams, 'service_id': str(service_id), 'intent': intent}), 202

@app.route('/serviceinfo/data', methods=['POST'])
def data():
    try:
        # Get the JSON data from the request
        data_from_client = request.get_json()

        #Hago lo que sea con la información del cliente
        print("PARÁMETROS DESDE CLIENTE RECOGIDOS")
        print(data_from_client)

        #Busco el server del servicio elegido.
        # Obtener el dominio del cliente
        domain = data_from_client["domain"]

        # Acceder a la colección dinámica basada en el dominio
        services_collection = db.get_collection(domain, 'services')

        # Busco el servicio por id en la colección correspondiente al dominio
        document = services_collection.find_one({"_id": ObjectId(data_from_client["service"])})

        document_str = str(document)
        data = json.dumps(document_str)

        service_url = data['servers'][0]['url']
        intent = data_from_client["intent"]
        filleddata = data_from_client["filledSlots"]
        #Añado el email del usuario
        filleddata["email"] = data_from_client["email"]

        # Cojo la ruta del server del JSON
        route = service_url + "/" + intent
        print(route)

        # Send the POST request
        response = requests.post(route, json=filleddata)

        # Check the response
        if response.status_code == 200:
            print("POST request was successful.")
            print("Response content:", response.text)
        else:
            print("POST request failed with status code:", response.status_code)

        #return jsonify({"message": "Data updated successfully"})

    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    """
    from flask_cors import CORS
    import ssl

    context = ssl.SSLContext()
    context.load_cert_chain("/home/mariajesus/certificados/conversational_ugr_es.pem",
                            "/home/mariajesus/certificados/conversational_ugr_es.key")
    CORS(app)
    app.run(host='0.0.0.0', port=5050, ssl_context=context, debug=False)
    """

    app.run()