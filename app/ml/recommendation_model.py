import pandas as pd
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier
import joblib
import os
import numpy as np


class RecommendationModel:
    def __init__(self):
        self.model = None
        self.label_encoder = LabelEncoder()
        self.features = [
            'verbal_accuracy',
            'selection_accuracy',
            'category_difficulty',
            'time_spent',
            'success_rate',
            'previous_attempts'
        ]
        self.model_path = 'app/ml/models/recommendation_model.pkl'
        self.encoder_path = 'app/ml/models/label_encoder.pkl'

        # Define some rule-based fallback categories
        self.fallback_categories = ['Animals', 'Food', 'Colors', 'Objects', 'Actions']

        if os.path.exists(self.model_path) and os.path.exists(self.encoder_path):
            self.model = joblib.load(self.model_path)
            self.label_encoder = joblib.load(self.encoder_path)
        else:
            self.model = XGBClassifier(use_label_encoder=False, eval_metric='mlogloss')
            self._initialize_with_dummy_data()

    def _initialize_with_dummy_data(self):
        """Create an initial model with dummy data if none exists."""
        dummy_data = pd.DataFrame([
            {
                'verbal_accuracy': 0.8,
                'selection_accuracy': 0.9,
                'category_difficulty': 1,
                'time_spent': 10,
                'success_rate': 0.85,
                'previous_attempts': 3,
                'recommended_category': 'Animals'
            },
            {
                'verbal_accuracy': 0.7,
                'selection_accuracy': 0.8,
                'category_difficulty': 2,
                'time_spent': 15,
                'success_rate': 0.75,
                'previous_attempts': 2,
                'recommended_category': 'Food'
            },
            {
                'verbal_accuracy': 0.6,
                'selection_accuracy': 0.7,
                'category_difficulty': 3,
                'time_spent': 20,
                'success_rate': 0.65,
                'previous_attempts': 1,
                'recommended_category': 'Colors'
            }
        ])

        X = dummy_data[self.features]
        y = dummy_data['recommended_category']

        self.label_encoder.fit(y)
        encoded_y = self.label_encoder.transform(y)

        self.model.fit(X, encoded_y)
        self.save_model()

    def _get_rule_based_recommendation(self, child_data: dict) -> str:
        """Fallback rule-based recommendation logic."""
        # Simple rules based on success rate
        success_rate = child_data.get('success_rate', 0)

        if success_rate > 0.8:
            return 'Actions'  # More challenging category
        elif success_rate > 0.6:
            return 'Objects'
        else:
            return 'Animals'  # Easier category

    def train(self, data: pd.DataFrame):
        """Train the model with new data."""
        X = data[self.features]
        y = data['recommended_category']

        existing_classes = set(self.label_encoder.classes_)
        new_classes = set(y.unique())

        if not new_classes.issubset(existing_classes):
            all_classes = sorted(list(existing_classes.union(new_classes)))
            self.label_encoder.fit(all_classes)

        encoded_y = self.label_encoder.transform(y)
        self.model.fit(X, encoded_y)
        self.save_model()

    def predict(self, child_data: dict) -> str:
        """Make a recommendation prediction for one child input."""
        input_data = pd.DataFrame([child_data])

        try:
            # Ensure all required features are present
            for feature in self.features:
                if feature not in input_data:
                    raise ValueError(f"Missing feature: {feature}")

            pred = self.model.predict(input_data[self.features])
            decoded_pred = self.label_encoder.inverse_transform(pred)
            return decoded_pred[0]
        except Exception as e:
            print(f"Model prediction failed, using rule-based fallback: {e}")
            return self._get_rule_based_recommendation(child_data)

    def save_model(self):
        """Save model and label encoder to disk."""
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        joblib.dump(self.model, self.model_path)
        joblib.dump(self.label_encoder, self.encoder_path)

    def update_model(self, session_data: pd.DataFrame):
        """Update the model with new session results."""
        try:
            existing_data = pd.read_csv('app/ml/data/training_data.csv')
            updated_data = pd.concat([existing_data, session_data], ignore_index=True)
        except FileNotFoundError:
            updated_data = session_data

        self.train(updated_data)
        updated_data.to_csv('app/ml/data/training_data.csv', index=False)