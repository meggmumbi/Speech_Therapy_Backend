import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
import joblib
import os
from datetime import datetime


class RecommendationModel:
    def __init__(self):
        self.model = None
        self.features = [
            'verbal_accuracy',
            'selection_accuracy',
            'category_difficulty',
            'time_spent',
            'success_rate',
            'previous_attempts'
        ]
        self.model_path = 'app/ml/models/recommendation_model.pkl'

        if os.path.exists(self.model_path):
            self.model = joblib.load(self.model_path)
        else:
            self.model = XGBClassifier()
            # Initialize with dummy data if no model exists
            self._initialize_with_dummy_data()

    def _initialize_with_dummy_data(self):
        """Create initial model with dummy data"""
        dummy_data = pd.DataFrame([{
            'verbal_accuracy': 0.8,
            'selection_accuracy': 0.9,
            'category_difficulty': 1,
            'time_spent': 10,
            'success_rate': 0.85,
            'previous_attempts': 3,
            'recommended_category': 'Animals'
        }])
        X = dummy_data[self.features]
        y = dummy_data['recommended_category']
        self.model.fit(X, y)
        self.save_model()

    def train(self, data: pd.DataFrame):
        """Train model with new data"""
        X = data[self.features]
        y = data['recommended_category']
        self.model.fit(X, y)
        self.save_model()

    def predict(self, child_data: dict):
        """Make recommendation prediction"""
        input_data = pd.DataFrame([child_data])
        return self.model.predict(input_data[self.features])[0]

    def save_model(self):
        """Save model to disk"""
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        joblib.dump(self.model, self.model_path)

    def update_model(self, session_data):
        """Update model with new session results"""
        # Convert session data to training format
        new_data = self._prepare_training_data(session_data)

        # Load existing training data
        try:
            existing_data = pd.read_csv('app/ml/data/training_data.csv')
            updated_data = pd.concat([existing_data, new_data])
        except FileNotFoundError:
            updated_data = new_data

        # Retrain model
        self.train(updated_data)
        updated_data.to_csv('app/ml/data/training_data.csv', index=False)