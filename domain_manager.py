import torch
from transformers import ConvBertForSequenceClassification, ConvBertTokenizer
from collections import Counter

# Ruta donde guardaste el checkpoint (ajusta según tu directorio)
checkpoint_dir = "./trained_model_epoch_3_step_5000"  # Cambia la ruta si usas otro checkpoint

# Cargar el tokenizador y el modelo
tokenizer = ConvBertTokenizer.from_pretrained(checkpoint_dir)
model = ConvBertForSequenceClassification.from_pretrained(checkpoint_dir,
                                                          state_dict=torch.load(f"{checkpoint_dir}/pytorch_model.bin"))

# Mover el modelo a la GPU (si está disponible) o a la CPU
device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
model.to(device)


# Definir una función para predecir el dominio usando el modelo cargado
def predict_domain(input_text):
    model.eval()  # Asegurarse de que el modelo esté en modo de evaluación
    inputs = tokenizer(input_text, return_tensors="pt", padding="max_length", truncation=True, max_length=128).to(
        device)

    with torch.no_grad():  # No calcular gradientes para la inferencia
        outputs = model(**inputs)
        logits = outputs.logits
        predicted_label = torch.argmax(logits, dim=-1).item()

    label_map = {0: "restaurant", 1: "hotel", 2: "attraction"}  # Mapea los resultados a los nombres de los dominios
    return label_map[predicted_label]


# 10 Frases de prueba
test_sentences = [
    "I want to book a table for two at a fancy restaurant.",
    "Can you recommend a good restaurant nearby?",
    "What is the best hotel to stay in New York?",
    "I would like to reserve a hotel room for the weekend.",
    "I want to visit some popular tourist attractions in Paris.",
    "Can you tell me about some attractions to see in Rome?",
    "Is there a good Italian restaurant in this area?",
    "I need a room for three nights at a hotel with a pool.",
    "What are the top tourist attractions in London?",
    "Where can I get the best pizza around here?"
]

# Probar el modelo con las 10 frases
for sentence in test_sentences:
    predicted_domain = predict_domain(sentence)
    print(f"Input: {sentence}")
    print(f"Predicted Domain: {predicted_domain}")
    print("-" * 50)