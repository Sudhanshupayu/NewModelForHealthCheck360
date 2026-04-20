"""Tests for the readiness scorer module."""

import pytest
from src.summarizer.readiness_scorer import (
    calculate_product_score,
    calculate_readiness_score,
    format_readiness_report,
    format_overview_summary,
    ProductReadiness,
)


class TestCalculateProductScore:
    """Tests for individual product score calculation."""
    
    def test_fully_ready(self):
        """All Yes should return 100."""
        assert calculate_product_score("Yes", "Yes", "Yes") == 100
    
    def test_two_yes(self):
        """Two Yes should return 66."""
        assert calculate_product_score("Yes", "No", "Yes") == 66
        assert calculate_product_score("Yes", "Yes", "No") == 66
        assert calculate_product_score("No", "Yes", "Yes") == 66
    
    def test_one_yes(self):
        """One Yes should return 33."""
        assert calculate_product_score("Yes", "No", "No") == 33
        assert calculate_product_score("No", "Yes", "No") == 33
        assert calculate_product_score("No", "No", "Yes") == 33
    
    def test_all_no(self):
        """All No should return 0."""
        assert calculate_product_score("No", "No", "No") == 0
    
    def test_case_insensitive(self):
        """Should handle different cases."""
        assert calculate_product_score("yes", "yes", "yes") == 100
        assert calculate_product_score("YES", "YES", "YES") == 100


class TestCalculateReadinessScore:
    """Tests for overall readiness calculation."""
    
    @pytest.fixture
    def sample_product_status(self):
        """Sample product status response."""
        return {
            "mid": "2",
            "product_status": {
                "Credit Card": {"flags": "Yes", "modes": "Yes", "status": "Yes"},
                "Debit Card": {"flags": "Yes", "modes": "Yes", "status": "Yes"},
                "UPI": {"flags": "Yes", "modes": "Yes", "status": "Yes"},
                "Mealcards": {"flags": "No", "modes": "No", "status": "No"},
                "S2S": {"flags": "Yes", "modes": "No", "status": "Yes"},
            }
        }
    
    def test_returns_mid(self, sample_product_status):
        """Should include MID in result."""
        result = calculate_readiness_score(sample_product_status)
        assert result["mid"] == "2"
    
    def test_calculates_overall_score(self, sample_product_status):
        """Should calculate correct overall score."""
        result = calculate_readiness_score(sample_product_status)
        # (100 + 100 + 100 + 0 + 66) / 5 = 73.2 → 73
        assert result["overall_score"] == 73
    
    def test_groups_by_category(self, sample_product_status):
        """Should group products by readiness category."""
        result = calculate_readiness_score(sample_product_status)
        
        assert len(result["fully_ready"]) == 3
        assert len(result["partially_ready"]) == 1
        assert len(result["not_configured"]) == 1
    
    def test_total_products_count(self, sample_product_status):
        """Should count total products correctly."""
        result = calculate_readiness_score(sample_product_status)
        assert result["total_products"] == 5
    
    def test_empty_product_status(self):
        """Should handle empty product status."""
        result = calculate_readiness_score({"mid": "1", "product_status": {}})
        assert result["overall_score"] == 0
        assert result["total_products"] == 0


class TestProductReadiness:
    """Tests for ProductReadiness dataclass."""
    
    def test_fully_ready_category(self):
        """Score 100 should be 'fully_ready'."""
        p = ProductReadiness("Test", 100, "Yes", "Yes", "Yes")
        assert p.category == "fully_ready"
    
    def test_partially_ready_category(self):
        """Score 66 should be 'partially_ready'."""
        p = ProductReadiness("Test", 66, "Yes", "No", "Yes")
        assert p.category == "partially_ready"
    
    def test_minimally_ready_category(self):
        """Score 33 should be 'minimally_ready'."""
        p = ProductReadiness("Test", 33, "Yes", "No", "No")
        assert p.category == "minimally_ready"
    
    def test_not_configured_category(self):
        """Score 0 should be 'not_configured'."""
        p = ProductReadiness("Test", 0, "No", "No", "No")
        assert p.category == "not_configured"


class TestFormatReadinessReport:
    """Tests for report formatting."""
    
    @pytest.fixture
    def sample_readiness_data(self):
        """Sample readiness data."""
        return {
            "mid": "2",
            "overall_score": 75,
            "total_products": 4,
            "fully_ready": [
                ProductReadiness("Credit Card", 100, "Yes", "Yes", "Yes"),
                ProductReadiness("UPI", 100, "Yes", "Yes", "Yes"),
            ],
            "partially_ready": [
                ProductReadiness("S2S", 66, "Yes", "No", "Yes"),
            ],
            "minimally_ready": [],
            "not_configured": [
                ProductReadiness("Mealcards", 0, "No", "No", "No"),
            ],
            "all_products": [],
        }
    
    def test_includes_mid(self, sample_readiness_data):
        """Report should include MID."""
        report = format_readiness_report(sample_readiness_data)
        assert "MID: 2" in report or "Merchant ID: 2" in report
    
    def test_includes_overall_score(self, sample_readiness_data):
        """Report should include overall score."""
        report = format_readiness_report(sample_readiness_data)
        assert "75%" in report
    
    def test_includes_merchant_name(self, sample_readiness_data):
        """Report should include merchant name if provided."""
        report = format_readiness_report(sample_readiness_data, "Test Merchant")
        assert "Test Merchant" in report
    
    def test_lists_fully_ready(self, sample_readiness_data):
        """Report should list fully ready products."""
        report = format_readiness_report(sample_readiness_data)
        assert "Credit Card" in report
        assert "UPI" in report
    
    def test_lists_not_configured(self, sample_readiness_data):
        """Report should list not configured products."""
        report = format_readiness_report(sample_readiness_data)
        assert "Mealcards" in report


class TestFormatOverviewSummary:
    """Tests for overview summary formatting."""
    
    @pytest.fixture
    def sample_overview(self):
        """Sample overview response."""
        return {
            "merchantInfo": {
                "mid": "2",
                "name": "Test Merchant Ltd",
                "key": "testkey",
                "approved": "Yes",
                "active": "Yes"
            },
            "kycStatus": {
                "merchantApprovalStatus": "Approved"
            },
            "onboardingStatus": {
                "onboardingStatus": "Approved",
                "midActivationStatus": "Active",
                "productsEnabled": "Credit Card, UPI"
            },
            "paymentApi": {
                "apiRateLimits": "100 Per Minute",
                "gmvLimits": "No limit"
            }
        }
    
    def test_includes_merchant_info(self, sample_overview):
        """Summary should include merchant info."""
        summary = format_overview_summary(sample_overview)
        assert "Test Merchant Ltd" in summary
        assert "testkey" in summary
    
    def test_includes_kyc_status(self, sample_overview):
        """Summary should include KYC status."""
        summary = format_overview_summary(sample_overview)
        assert "Approved" in summary
    
    def test_includes_api_limits(self, sample_overview):
        """Summary should include API limits."""
        summary = format_overview_summary(sample_overview)
        assert "100 Per Minute" in summary
