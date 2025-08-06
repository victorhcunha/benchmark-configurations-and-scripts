from zipfile import ZipFile
import numpy as np
import cv2
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression


def load_and_crop_image(image, top_half=True):
    if image is None:
        raise ValueError("Image is None, cannot crop.")
    height = image.shape[0]
    width = image.shape[1]
    if top_half:
        return image[0:height // 4, 2 * width // 5:]
    else:
        return image[height // 2:, :]


def extract_color_mask(image, lower_hsv, upper_hsv):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, lower_hsv, upper_hsv)


def extract_red_mask(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_red1 = np.array([0, 70, 50])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([170, 70, 50])
    upper_red2 = np.array([180, 255, 255])
    return cv2.inRange(hsv, lower_red1, upper_red1) | cv2.inRange(hsv, lower_red2, upper_red2)


def fit_trend_line(xs, ys):
    if len(xs) == 0 or len(ys) == 0:
        raise ValueError("No data points to fit.")
    X = xs.reshape(-1, 1)
    model = LinearRegression().fit(X, ys)
    return model


def plot_trend(image, xs, model, title, output_path=None):
    plt.figure(figsize=(10, 5))
    plt.imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    plt.plot(xs, model.predict(xs.reshape(-1, 1)), color='red', linewidth=2, label='Trend Line')
    plt.title(title)
    plt.legend()
    if output_path:
        plt.savefig(output_path)
        plt.close()
    else:
        plt.show()


def analyze_trend_slope(slope):
    if slope < -0.5:
        return "down"
    elif slope > 0.5:
        return "up"
    elif slope < -0.05:
        return "slightly down"
    elif slope > 0.05:
        return "slightly up"
    else:
        return "flat"


def get_session_trend(image):
    top_chart = load_and_crop_image(image, top_half=True)

    # Try blue line first
    blue_mask = extract_color_mask(
        # Use a wider HSV color range to reliably capture the blue line
        top_chart, lower_hsv=np.array([90, 100, 0]), upper_hsv=np.array([150, 255, 255])
    )
    ys_blue_all, xs_blue_all = np.where(blue_mask > 0)

    if len(xs_blue_all) > 0 and len(ys_blue_all) > 0:
        points = sorted(zip(xs_blue_all, ys_blue_all))

        # Take the last portion of the points (10% from the end)
        final_points_count = int(len(points) * 0.15)
        if final_points_count < 10:
            final_points_count = len(points)
        final_points = points[-final_points_count:]

        xs_blue = np.array([p[0] for p in final_points])
        ys_blue = np.array([p[1] for p in final_points])

        if len(xs_blue) > 0 and len(ys_blue) > 0:
            blue_model = fit_trend_line(xs_blue, ys_blue)
            blue_slope = blue_model.coef_[0]
            print("Current Session Count -> Blue slope:", blue_slope)

            # Invert the slope sign because the Y-axis in image coordinates increases downwards
            blue_slope = -blue_slope

            if abs(blue_slope) > 0.03:  # Not flat (avoid false 0.0 due to noise)
                plot_trend(top_chart, xs_blue, blue_model, f'Blue Line Trend (slope: {blue_slope:.2f})', output_path="tendency.png")
                return analyze_trend_slope(blue_slope)

    print("Blue slope is 0.0 or data is insufficient. Falling back to red line.")
    red_mask = extract_red_mask(top_chart)
    ys_red, xs_red = np.where(red_mask > 0)

    if len(xs_red) == 0 or len(ys_red) == 0:
        raise ValueError("No valid data points found for red line.")

    red_model = fit_trend_line(xs_red, ys_red)
    red_slope = red_model.coef_[0]
    print("Average Session Count -> Red slope:", red_slope)
    
    # Invert the slope sign for the red line as well
    red_slope = -red_slope

    plot_trend(top_chart, xs_red, red_model, f'Red Line Trend (slope: {red_slope:.2f})', output_path="tendency.png")
    return analyze_trend_slope(red_slope)


def analyze_session_trend(zip_path, file_path):
    with ZipFile(zip_path, 'r') as zip_file_content:
        with zip_file_content.open(file_path) as image_file:
            image_data = image_file.read()
            image_array = np.frombuffer(image_data, np.uint8)
            image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Could not decode image from zip.")
            return get_session_trend(image)