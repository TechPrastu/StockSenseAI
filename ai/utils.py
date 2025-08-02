# filepath: /mnt/d/TechPrastu/GitHub/StockSenseAI/ai/utils.py
def load_data(*args, **kwargs):
    pass

def preprocess_data(*args, **kwargs):
    pass

def normalize_data(*args, **kwargs):
    pass

def normalize_data(data):
    return (data - data.mean()) / data.std()

def extract_features(data):
    features = data[['Open', 'High', 'Low', 'Close', 'Volume']]
    return features

def split_data(data, train_size=0.8):
    train_size = int(len(data) * train_size)
    train_data = data[:train_size]
    test_data = data[train_size:]
    return train_data, test_data

def prepare_data_for_model(data):
    features = extract_features(data)
    labels = data['Close'].shift(-1).dropna()
    features = features[:-1]  # Align features with labels
    return features, labels

def calculate_rmse(predictions, actuals):
    return ((predictions - actuals) ** 2).mean() ** 0.5
