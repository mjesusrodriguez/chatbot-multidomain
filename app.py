from bson import ObjectId
from flask import Flask, render_template, request, jsonify
import json
import random
import requests

from domain_manager import predict_domain
from intentrec import intentRecWithChatGPT2
from mongo_config import get_database
from openai_config import setup_openai
from questionimprovement import improveQuestionchatGPT
from questionretrieval import questionsRetrieval
from slotfilling import extractSlots, slotFillingGPT
from tagfilter import tagFilter, getAditionalQuestions

app = Flask(__name__)

# Obtener la base de datos
db = get_database()
# Obtener la colección de servicios de restaurantes
restaurant_sv = db.restaurant

model_engine = setup_openai()

#Variable global para guardar el servicio
service_id = ""
#variable global para guardar el intent
intent = ""

#Devolver los servicios filtrados según los tags que contengan
def filterServicesByTag(intentServices, userTags):
    #tagServices = []
    services = {}

    for service_id in intentServices:
        #Busco el servicio por id
        document = restaurant_sv.find_one({"_id": ObjectId(service_id)})

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

@app.route('/')
def index():
    return render_template('chat.html')

#PRIMERA INTERACCIÓN CON EL USUARIO
@app.route('/intent', methods=['POST'])
def intentrec():
    questions = {}
    filledParams = {'pricerange': '', 'food': ''}  # Inicializo respuestas vacías

    # Obtener datos del cuerpo de la solicitud POST
    data = request.get_json()  # Utiliza get_json() para obtener datos JSON
    # Verificar si se recibieron datos
    if not data:
        return jsonify({"error": "No data received"}), 400

    # Extraer los datos recibidos
    userInput = data.get('userinput')
    print(userInput)

    #predicción de dominio
    domain = predict_domain(userInput)
    print("DOMAIN: ", domain)
    userAnswers = data.get('answers')

    # Reconocimiento de intent - Servicio intentrec
    user_intent = intentRecWithChatGPT2(userInput)
    intent = user_intent.lower()
    print(intent)

    #Voy a ver que slots me da ya el usuario - Servicio requiredslots
    reqSlots = ["pricerange", "food"]

    if not isinstance(userInput, str):
        raise TypeError(f"Expected 'input' to be of type 'str', got {type(userInput)}")

    if not isinstance(reqSlots, list):
        raise TypeError(f"Expected 'slots' to be of type 'list', got {type(reqSlots)}")


    slots = slotFillingGPT(userInput, reqSlots)
    print("Slots generados:", slots)

    # Initialize lists to store null and non-null parameters
    null_params = []

    # Verifica si slots es una cadena y convierte en lista de diccionarios
    if isinstance(slots, str):
        try:
            slots_list = json.loads(slots)  # Convertir de cadena JSON a lista de diccionarios
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format for 'slots': {e}")
    else:
        slots_list = slots

    try:
        # Verify if slots is a string and convert it into a list of dictionaries
        if isinstance(slots, str):
            try:
                slots_data = json.loads(slots)  # Convert from JSON string to Python object
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON format for 'slots': {e}")
        else:
            slots_data = slots

        # Ensure slots_data is a list of dictionaries
        if isinstance(slots_data, dict):
            # If slots_data is a dictionary, wrap it in a list
            slots_list = [slots_data]
        elif isinstance(slots_data, list):
            slots_list = slots_data
        else:
            raise TypeError(f"Expected 'slots_data' to be of type 'list' or 'dict', got {type(slots_data)}")

        for slots_dict in slots_list:
            if isinstance(slots_dict, dict):
                # Iterate through the dictionary and categorize parameters
                for param, value in slots_dict.items():
                    if value == "Null":
                        null_params.append(param)
                    else:
                        filledParams[param] = value
            else:
                print(f"Unexpected data type in slots_list: {type(slots_dict)}")

    except Exception as e:
        print(f"An error occurred: {e}")

    # Create a string for each non-null parameter and append it to the questions vector
    for param in null_params:
        if (param == 'pricerange'):
            questions['pricerange'] = improveQuestionchatGPT("What is the pricerange of the restaurant you are looking for?")
        if (param == 'food'):
            questions['food'] = improveQuestionchatGPT("Which is the kind of food you want to eat?")

    return jsonify({'questions': questions, 'filled': filledParams, 'intent': intent, 'userinput': userInput}), 202

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
    userInput = data_from_client["userinput"]
    userAnswers = data_from_client.get('useranswers', [])

    price = data_from_client["filledSlots"]["pricerange"]
    cuisinetype = data_from_client["filledSlots"]["food"]

    #Selecciono un servicio - Servicio TagFilter
    services = tagFilter(userInput, intent, data_from_client)
    print("FILTRO POR CAMPOS OBLIGATORIOS")
    print(services)

    # Voy a coger los parámetros discriminatorios de los servicios si son más de uno.
    if len(services) > 1:
        aditional_questions, filledParams = getAditionalQuestions(services, userInput, intent, data_from_client)
        return jsonify(
            {'questions': aditional_questions, 'filled': filledParams, 'intent': intent, 'userinput': userInput, 'services': [str(service) for service in services], 'useranswers': userAnswers}), 202

    else:
        # Selecciono el que se ha devuelto
        service_id = services[0]
        ##########################################
        # consulto en los servicios que tengo que campos se han rellenado ya y cuales faltan y devuelvo las preguntas.
        #slotFillingResponse = impSlotFillingChatGPT(userInput, service_id, intent, userAnswers)
        slots = extractSlots(intent, service_id)
        slotFillingResponse = slotFillingGPT(userInput, slots, userAnswers)

        # Convert the string to a dictionary
        sf_data = json.loads(slotFillingResponse)

        for key, value in sf_data.items():
            if value == "Null":
                emptyParams[key] = value
            else:
                filledParams[key] = value

        #Quitamos food y pricerange del vector.
        if "pricerange" in emptyParams:
            emptyParams.pop("pricerange")

        if "food" in emptyParams:
            emptyParams.pop("food")

        print("EMPTY PARAMS")
        print(emptyParams)

        #Para evitar posibles errores voy a poner los filled params del principio
        filledParams["pricerange"] = price
        filledParams["food"] = cuisinetype

        print("FILLED PARAMS")
        print(filledParams)

        # hago una llamada a la función que dado un intent y un id me da las preguntas.
        intent_info = questionsRetrieval(service_id, intent)

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
            {'questions': questions, 'filled': filledParams, 'service_id': str(service_id), 'intent': intent, 'useranswers': userAnswers}), 202

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

    price = data_from_client["filledSlots"]["pricerange"]
    cuisinetype = data_from_client["filledSlots"]["food"]

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
    selected_services = filterServicesByTag(services, positive_tags)
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
    slots = extractSlots(intent, service_id)

    # Le paso los slots a la tarea de SF, como es una tercera interacción, voy a pasarle el histórico del diálogo, para que rellene también
    # según ha contestado en las preguntas intermedias.
    slotFillingResponse = slotFillingGPT(userInput, slots, userAnswers)
    print("Los slots rellenos con el cambio son:" + slotFillingResponse)

    # Convert the string to a dictionary
    sf_data = json.loads(slotFillingResponse)

    for key, value in sf_data.items():
        if value == "Null":
            emptyParams[key] = value
        else:
            filledParams[key] = value

    # Quitamos food y pricerange del vector.
    if "pricerange" in emptyParams:
        emptyParams.pop("pricerange")

    if "food" in emptyParams:
        emptyParams.pop("food")

    print("EMPTY PARAMS")
    print(emptyParams)

    # Para evitar posibles errores voy a poner los filled params del principio
    filledParams["pricerange"] = price
    filledParams["food"] = cuisinetype

    print("FILLED PARAMS")
    print(filledParams)

    # hago una llamada a la función que dado un intent y un id me da las preguntas.
    intent_info = questionsRetrieval(service_id, intent)

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
        # Busco el servicio por id
        document = restaurant_sv.find_one({"_id": ObjectId(data_from_client["service"])})
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