import random
from bson import ObjectId
from mongo_config import get_database
from openai_config import setup_openai

model_engine = setup_openai()

# Obtener la base de datos
db = get_database()
# Obtener la colección de servicios de restaurantes
restaurant_sv = db.restaurant

def serviceSelection(tagServices, user_input, slots, intent):
    service_descriptions = {}
    # Cojo los servicios con los valores máximo del vector
    max_value = max(tagServices.values())
    max_keys = [key for key, value in tagServices.items() if value == max_value]
    selected_services = []

    # Miro a ver cuantos servicios han salido con etiquetas máximas
    # Si es mayor que uno
    if len(max_keys) > 1:
        print("Entro porque hay más de un servicio")
        for service_id in max_keys:
            print("Servicio a estudiar")
            print(service_id)
            # Busco el servicio por id
            document = restaurant_sv.find_one({"_id": ObjectId(service_id)})

            # Check if the document exists and contains 'paths'
            if document and 'paths' in document:
                # Initialize example values
                pricerange_example = None
                food_example = None

                # Check for both 'get' and 'post' methods
                methods = []
                if "/bookrestaurant" in document["paths"]:
                    if "get" in document["paths"]["/bookrestaurant"]:
                        methods.append("get")
                    if "post" in document["paths"]["/bookrestaurant"]:
                        methods.append("post")

                # Iterate over available methods
                for method in methods:
                    parameters = document["paths"]["/bookrestaurant"][method].get("parameters", [])

                    # Iterate through the parameters list to find pricerange and food
                    for param in parameters:
                        if param["name"] == "pricerange" and "value" in param["schema"]:
                            pricerange_example = param["schema"]["value"]
                        elif param["name"] == "food" and "value" in param["schema"]:
                            food_example = param["schema"]["value"]

                    # Check if both example values were found
                    if pricerange_example and food_example:
                        # Do something with the example values
                        print("Example pricerange:", pricerange_example)
                        print("Example food:", food_example)

                        # Aquí cojo los servicios que tengan el pricerange y el foodtype que me ha dado el usuario
                        if pricerange_example == slots.get("pricerange") or food_example == slots.get("food"):
                            print("ENTRO EN EL IF con los valores anteriores")
                            selected_services.append(service_id)

    else:
        selected_services = [max_keys[0]]

    if not selected_services:
        random_service = random.choice(list(tagServices.keys()))
        selected_services.append(random_service)

    print("SELECTED SERVICES")
    print(selected_services)
    return selected_services

def selectServiceByIntent(intent):
    services = []

    #cojo todos los elementos de la base de datos de mongo
    all_services = restaurant_sv.find({'paths': {'$exists': True}})
    print(all_services)
    for document in all_services:
        for i in document['paths']:
            # Check if the 'paths' field exists and is a dictionary
            if 'paths' in document and isinstance(document['paths'], dict):
                # Iterate over each path in the document
                for path, _ in document['paths'].items():
                    # Remove the leading '/' character from the path
                    intent_name_without_char = path.lstrip('/')
                    if (intent_name_without_char == intent):
                        services.append(document['_id'])
    return services
